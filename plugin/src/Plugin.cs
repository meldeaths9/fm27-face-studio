// FM27 Face Studio 플러그인
// - 실시간 반영: 프로그램이 "refresh"를 요청하면 게임이 사용자 graphics 폴더(config.xml 포함)를 다시 읽게 한다.
// - 진단: 게임이 요청하는 사진 키와 데이터 바인딩 구조를 기록해 감독 사진·지원 스태프 작업에 쓴다.
// 프로그램과는 %APPDATA%\FM27FacePicker\plugin 폴더의 작은 JSON 파일로만 주고받는다.
using System.Text;
using System.Text.Json;
using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Il2CppInterop.Runtime;
using SI.Core;
using DateTime = System.DateTime;
using UnityEngine;

namespace FaceStudio;

[BepInPlugin(Id, Name, Version)]
public sealed class Plugin : BasePlugin
{
    public const string Id = "kr.fm27facestudio.plugin";
    public const string Name = "FM27 Face Studio";
    public const string Version = "0.1.0";

    internal static ManualLogSource L = null!;
    internal static Harmony H = null!;

    public override void Load()
    {
        L = Log;
        H = new Harmony(Id);
        Bridge.Init();
        AddComponent<Runner>();
        L.LogInfo($"{Name} {Version} 준비됨 — 통신 폴더: {Bridge.Dir}");
    }
}

/// <summary>프로그램과 주고받는 파일들.</summary>
internal static class Bridge
{
    public static string Dir = "";
    public static string StatusFile => Path.Combine(Dir, "status.json");
    public static string CommandFile => Path.Combine(Dir, "command.json");
    public static string ResultFile => Path.Combine(Dir, "result.json");
    public static string DiagDir => Path.Combine(Dir, "diag");

    public static void Init()
    {
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        Dir = Path.Combine(appData, "FM27FacePicker", "plugin");
        Directory.CreateDirectory(Dir);
        Directory.CreateDirectory(DiagDir);
    }

    public static void WriteJson(string path, object value)
    {
        var tmp = path + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(value, new JsonSerializerOptions { WriteIndented = true }), Encoding.UTF8);
        File.Move(tmp, path, true);
    }
}

public sealed class Runner : MonoBehaviour
{
    private float _nextPoll;
    private float _nextBeat;
    private string _lastCommandId = "";
    private string _lastResult = "";

    public Runner(IntPtr pointer) : base(pointer) { }

    public void Update()
    {
        var now = Time.realtimeSinceStartup;
        if (now >= _nextBeat)
        {
            _nextBeat = now + 2f;
            Heartbeat();
        }
        if (now >= _nextPoll)
        {
            _nextPoll = now + 0.4f;
            PollCommand();
        }
        Diag.Tick(now);
    }

    private void Heartbeat()
    {
        try
        {
            Bridge.WriteJson(Bridge.StatusFile, new
            {
                plugin = Plugin.Version,
                pid = Environment.ProcessId,
                time = DateTimeOffset.Now.ToUnixTimeSeconds(),
                resources = Refresher.Find() is not null,
                diagnosing = Diag.Active,
                last = _lastResult,
            });
        }
        catch (Exception e)
        {
            Plugin.L.LogWarning("상태 기록 실패: " + e.Message);
        }
    }

    private void PollCommand()
    {
        string text;
        try
        {
            if (!File.Exists(Bridge.CommandFile)) return;
            text = File.ReadAllText(Bridge.CommandFile, Encoding.UTF8);
            File.Delete(Bridge.CommandFile);
        }
        catch (IOException) { return; }   // 프로그램이 쓰는 중

        string id = "", cmd = "";
        int seconds = 120;
        try
        {
            using var doc = JsonDocument.Parse(text);
            id = doc.RootElement.TryGetProperty("id", out var v1) ? v1.GetString() ?? "" : "";
            cmd = doc.RootElement.TryGetProperty("cmd", out var v2) ? v2.GetString() ?? "" : "";
            if (doc.RootElement.TryGetProperty("seconds", out var v3) && v3.TryGetInt32(out var s)) seconds = s;
        }
        catch (Exception e)
        {
            Answer(id, false, "명령을 읽지 못했어요: " + e.Message);
            return;
        }
        if (id == _lastCommandId) return;
        _lastCommandId = id;

        try
        {
            switch (cmd)
            {
                case "ping":
                    Answer(id, true, "연결됨");
                    break;
                case "refresh":
                    Refresher.Refresh(ok => Answer(id, ok.ok, ok.message));
                    break;
                case "diag":
                    Answer(id, true, Diag.Start(seconds));
                    break;
                case "diag_stop":
                    Answer(id, true, Diag.Stop());
                    break;
                default:
                    Answer(id, false, "모르는 명령: " + cmd);
                    break;
            }
        }
        catch (Exception e)
        {
            Plugin.L.LogError($"명령 {cmd} 실패: {e}");
            Answer(id, false, $"{cmd} 실패: {e.GetType().Name}: {e.Message}");
        }
    }

    private void Answer(string id, bool ok, string message)
    {
        _lastResult = message;
        Plugin.L.LogInfo($"[{id}] {(ok ? "성공" : "실패")}: {message}");
        try
        {
            Bridge.WriteJson(Bridge.ResultFile, new { id, ok, message, time = DateTimeOffset.Now.ToUnixTimeSeconds() });
        }
        catch (Exception e)
        {
            Plugin.L.LogWarning("결과 기록 실패: " + e.Message);
        }
    }
}

/// <summary>게임의 리소스 시스템에 사용자 graphics 폴더를 다시 검사하게 한다.</summary>
internal static class Refresher
{
    private static ResourcesSubsystem? _cached;

    public static ResourcesSubsystem? Find()
    {
        try
        {
            if (_cached is not null && _cached.Pointer != IntPtr.Zero) return _cached;
            var found = UnityEngine.Object.FindObjectsOfType(Il2CppType.Of<ResourcesSubsystem>());
            if (found is not null && found.Length > 0)
            {
                _cached = found[0].Cast<ResourcesSubsystem>();
                return _cached;
            }
        }
        catch (Exception e)
        {
            Plugin.L.LogWarning("리소스 시스템 찾기 실패: " + e.Message);
        }
        return null;
    }

    public static void Refresh(Action<(bool ok, string message)> done)
    {
        var rs = Find();
        if (rs is null)
        {
            done((false, "게임의 리소스 시스템을 찾지 못했어요. 세이브를 불러온 뒤 다시 시도해 주세요."));
            return;
        }
        var started = DateTime.Now;
        var callback = DelegateSupport.ConvertDelegate<Il2CppSystem.Action>(new Action(() =>
        {
            try
            {
                rs.ClearCache();
                var ms = (int)(DateTime.Now - started).TotalMilliseconds;
                done((true, $"graphics 폴더를 다시 읽었어요 ({ms}ms). 다른 화면으로 갔다 오면 바뀐 사진이 보여요."));
            }
            catch (Exception e)
            {
                done((false, "다시 읽은 뒤 캐시 비우기 실패: " + e.Message));
            }
        }));
        rs.RescanLocalPaths(callback);
        Plugin.L.LogInfo("graphics 폴더 다시 검사 시작");
    }
}

/// <summary>진단: 게임이 요청하는 사진 키, 바인딩 구조를 파일로 남긴다.</summary>
internal static class Diag
{
    public static bool Active;
    private static float _until;
    private static readonly HashSet<string> Seen = new();
    private static readonly StringBuilder Keys = new();
    private static readonly List<System.Reflection.MethodBase> Patched = new();
    private static string _file = "";

    public static string Start(int seconds)
    {
        if (Active) return "이미 진단 중이에요.";
        Seen.Clear();
        Keys.Clear();
        _until = Time.realtimeSinceStartup + Math.Clamp(seconds, 10, 900);
        _file = Path.Combine(Bridge.DiagDir, $"diag-{DateTime.Now:yyyyMMdd-HHmmss}.txt");
        var report = new StringBuilder();
        report.AppendLine($"FM27 Face Studio 진단 {DateTime.Now:yyyy-MM-dd HH:mm:ss}, plugin {Plugin.Version}");
        report.AppendLine($"Unity {Application.unityVersion}, game {Application.version}");
        report.AppendLine();
        report.AppendLine("== 바인딩 루트 ==");
        report.Append(BindingDump.Roots());
        File.WriteAllText(_file, report.ToString(), Encoding.UTF8);

        foreach (var name in new[] { "ResolveKey", "Locate" })
        {
            foreach (var m in AccessTools.GetDeclaredMethods(typeof(ResourcesSubsystem)).Where(m => m.Name == name))
            {
                try
                {
                    var prefix = new HarmonyMethod(typeof(Diag).GetMethod(nameof(KeyPrefix), System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic));
                    Plugin.H.Patch(m, prefix: prefix);
                    Patched.Add(m);
                }
                catch (Exception e)
                {
                    Plugin.L.LogWarning($"{name} 감시 설정 실패: {e.Message}");
                }
            }
        }
        Active = true;
        return $"진단 시작 ({seconds}초). 그동안 내 감독 프로필, 지원 스태프(언론 담당자 등) 프로필, 사진이 바뀌어야 할 선수 프로필을 차례로 열어 주세요. 감시 {Patched.Count}곳.";
    }

    // ResolveKey(object key) / Locate(object key, Type type, object x) 첫 인자가 키
    private static void KeyPrefix(Il2CppSystem.Object __0)
    {
        if (!Active || __0 is null) return;
        try
        {
            var s = __0.ToString();
            if (s is null || s.Length > 300 || !Seen.Add(s)) return;
            if (Seen.Count > 20000) return;
            Keys.AppendLine($"{DateTime.Now:HH:mm:ss}  {s}");
        }
        catch
        {
            // 진단 중 오류는 무시
        }
    }

    public static void Tick(float now)
    {
        if (Active && now >= _until) Stop();
    }

    public static string Stop()
    {
        if (!Active) return "진단 중이 아니에요.";
        Active = false;
        foreach (var m in Patched)
        {
            try { Plugin.H.Unpatch(m, HarmonyPatchType.Prefix, Plugin.H.Id); } catch { }
        }
        Patched.Clear();
        var report = new StringBuilder();
        report.AppendLine();
        report.AppendLine($"== 요청된 리소스 키 ({Seen.Count}개, 처음 본 순서) ==");
        report.Append(Keys);
        report.AppendLine();
        report.AppendLine("== 바인딩 Human (깊이 3) ==");
        report.Append(BindingDump.Path("Human", 3));
        File.AppendAllText(_file, report.ToString(), Encoding.UTF8);
        Plugin.L.LogInfo("진단 파일: " + _file);
        return "진단 끝. 파일: " + _file;
    }
}

/// <summary>게임 UI 데이터 바인딩 트리의 이름 구조만 적는다 (값은 읽지 않음).</summary>
internal static class BindingDump
{
    private static SI.Bindable.Bindings.Node? Root()
    {
        try { return FM.UI.EmbeddedDataHandler.s_bindingSubsystem?.m_root; }
        catch { return null; }
    }

    public static string Roots()
    {
        var root = Root();
        if (root is null) return "(바인딩 시스템이 아직 없음)\n";
        var sb = new StringBuilder();
        for (var n = root.m_firstChild; n is not null; n = n.m_nextSibling)
            sb.AppendLine($"  {n.m_name} [{Count(n)}]");
        return sb.ToString();
    }

    public static string Path(string path, int depth)
    {
        var node = Root();
        if (node is null) return "(바인딩 시스템이 아직 없음)\n";
        foreach (var seg in path.Split('.'))
        {
            SI.Bindable.Bindings.Node? next = null;
            for (var c = node.m_firstChild; c is not null; c = c.m_nextSibling)
                if (string.Equals(c.m_name, seg, StringComparison.OrdinalIgnoreCase)) { next = c; break; }
            if (next is null) return $"('{seg}' 없음)\n";
            node = next;
        }
        var sb = new StringBuilder();
        Append(sb, node, 0, depth);
        return sb.ToString();
    }

    private static int Count(SI.Bindable.Bindings.Node n)
    {
        var i = 0;
        for (var c = n.m_firstChild; c is not null && i < 100000; c = c.m_nextSibling) i++;
        return i;
    }

    private static void Append(StringBuilder sb, SI.Bindable.Bindings.Node n, int indent, int depth)
    {
        sb.Append(' ', indent * 2).AppendLine($"{n.m_name} [{Count(n)}]");
        if (depth <= 0) return;
        var i = 0;
        for (var c = n.m_firstChild; c is not null; c = c.m_nextSibling)
        {
            if (i++ >= 300) { sb.Append(' ', (indent + 1) * 2).AppendLine("…"); break; }
            Append(sb, c, indent + 1, depth - 1);
        }
    }
}
