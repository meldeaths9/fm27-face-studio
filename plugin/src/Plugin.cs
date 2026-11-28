// FM Face Studio 플러그인
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
    public const string Name = "FM Face Studio";
    public const string Version = "0.8.1";

    internal static ManualLogSource L = null!;
    internal static Harmony H = null!;

    public override void Load()
    {
        L = Log;
        H = new Harmony(Id);
        Bridge.Init();
        AddComponent<Runner>();
        ManagerFace.Install();
        Appearance.Install();
        Kits.Install();
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
        File.WriteAllText(tmp, JsonSerializer.Serialize(value, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
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
        Appearance.Tick(now);
        Collect.Tick(now);
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
                manager_photo = ManagerFace.HasPhoto,
                manager_hits = ManagerFace.Hits,
                manager_shots = ManagerFace.Shots,
                appearance_count = Appearance.Count,
                collecting = Collect.On,
                kits = Kits.Count,
                collected = Collect.Count,
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
                case "collect":
                    Answer(id, true, Collect.Start(seconds));
                    break;
                case "collect_stop":
                    Answer(id, true, Collect.Stop());
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
    private static readonly List<(System.Reflection.MethodBase target, System.Reflection.MethodInfo patch)> Patched = new();
    private static string _file = "";

    public static string Start(int seconds)
    {
        if (Active) return "이미 진단 중이에요.";
        Seen.Clear();
        Keys.Clear();
        Calls.Clear();
        _callCount = 0;
        _until = Time.realtimeSinceStartup + Math.Clamp(seconds, 10, 900);
        _file = Path.Combine(Bridge.DiagDir, $"diag-{DateTime.Now:yyyyMMdd-HHmmss}.txt");
        var report = new StringBuilder();
        report.AppendLine($"FM Face Studio 진단 {DateTime.Now:yyyy-MM-dd HH:mm:ss}, plugin {Plugin.Version}");
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
                    var pm = typeof(Diag).GetMethod(nameof(KeyPrefix), System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
                    Plugin.H.Patch(m, prefix: new HarmonyMethod(pm));
                    Patched.Add((m, pm));
                }
                catch (Exception e)
                {
                    Plugin.L.LogWarning($"{name} 감시 설정 실패: {e.Message}");
                }
            }
        }
        // 2판: 사람 사진 주소를 만드는 곳과 실제로 그림을 거는 곳을 따라간다.
        var traced = new (Type t, string[] names)[]
        {
            (typeof(FM.UI.DatabaseObjectImageHelpers), new[] { "ConvertObjectIDToAddressableID", "ConvertDynamicReferenceToAddressableID", "EncodeNewgenAppearanceDescription" }),
            (typeof(SI.Bindable.SIImage), new[] { "SetImage" }),
            (typeof(FM.UI.NewGenPortraitResourceLocator), new[] { "Locate", "PrepareGeneration" }),
            (typeof(FM.UI.NewGenPortraitManager), new[] { "GetIDFromResourceID", "GetNewgenFromResourceIDAsync" }),
            (typeof(FM.UI.NewGenPortraitTextureLoader), new[] { "DecodeKey", "FindBestPortrait" }),

        };
        foreach (var (t, names) in traced)
        {
            foreach (var m in AccessTools.GetDeclaredMethods(t).Where(m => names.Contains(m.Name)))
            {
                try
                {
                    var ret = (m as System.Reflection.MethodInfo)?.ReturnType;
                    var withResult = ret is not null && ret != typeof(void) && !ret.IsValueType;
                    var pm = typeof(Diag).GetMethod(withResult ? nameof(TracePostR) : nameof(TracePost),
                        System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
                    Plugin.H.Patch(m, postfix: new HarmonyMethod(pm));
                    Patched.Add((m, pm));
                }
                catch (Exception e)
                {
                    Calls.AppendLine($"(감시 실패) {t.Name}.{m.Name}: {e.Message}");
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

    private static readonly StringBuilder Calls = new();
    private static int _callCount;

    private static void TracePost(System.Reflection.MethodBase __originalMethod, object[] __args) => Trace(__originalMethod, __args, null, false);
    private static void TracePostR(System.Reflection.MethodBase __originalMethod, object[] __args, object __result) => Trace(__originalMethod, __args, __result, true);

    private static void Trace(System.Reflection.MethodBase m, object[] args, object? result, bool hasResult)
    {
        if (!Active) return;
        try
        {
            var sb = new StringBuilder();
            sb.Append(m.DeclaringType?.Name).Append('.').Append(m.Name).Append('(');
            for (var i = 0; i < (args?.Length ?? 0); i++)
            {
                if (i > 0) sb.Append(", ");
                sb.Append(Describe(args![i]));
            }
            sb.Append(')');
            if (hasResult) sb.Append(" => ").Append(Describe(result));
            var line = sb.ToString();
            if (line.Length > 600) line = line[..600];
            if (!Seen.Add("C|" + line) || ++_callCount > 5000) return;
            Calls.AppendLine($"{DateTime.Now:HH:mm:ss}  {line}");
        }
        catch (Exception e)
        {
            if (Seen.Add("E|" + m.Name)) Calls.AppendLine($"(기록 실패) {m.Name}: {e.Message}");
        }
    }

    private static string Describe(object? o)
    {
        if (o is null) return "null";
        try
        {
            switch (o)
            {
                case string str: return "\"" + str + "\"";
                case SI.Bindable.DynamicReference dr:
                {
                    string id = "?", txt = "";
                    try { id = dr.ID.ToString(); } catch { }
                    try { txt = dr.ToString(); } catch { }
                    return $"DynRef(ID={id}, {txt})";
                }
                case Texture tx:
                {
                    string n = "", sz = "";
                    try { n = tx.name; } catch { }
                    try { sz = $"{tx.width}x{tx.height}"; } catch { }
                    return $"{tx.GetIl2CppType()?.Name}('{n}' {sz})";
                }
                case Il2CppSystem.Object io:
                {
                    var tn = io.GetIl2CppType()?.Name ?? "?";
                    string v = "";
                    try { v = io.ToString(); } catch { }
                    return v == tn || string.IsNullOrEmpty(v) ? tn : $"{tn}:{v}";
                }
                default: return o.ToString() ?? "?";
            }
        }
        catch
        {
            return o.GetType().Name;
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
        foreach (var (m, pm) in Patched)
        {
            try { Plugin.H.Unpatch(m, pm); } catch { }   // 진단용만 떼고 감독 사진 연결은 그대로 둔다
        }
        Patched.Clear();
        var report = new StringBuilder();
        report.AppendLine();
        report.AppendLine($"== 요청된 리소스 키 ({Seen.Count}개, 처음 본 순서) ==");
        report.Append(Keys);
        report.AppendLine();
        report.AppendLine($"== 사진 경로 추적 ({_callCount}건, 같은 내용은 한 번만) ==");
        report.Append(Calls);
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


/// <summary>
/// 내 감독 사진: FM27은 감독 외모 편집에서 만든 3D 캐릭터를 그 자리에서 찍어(ManagerCloseupShot) 쓴다.
/// 프로그램이 manager.raw(가로·세로 + RGBA, 아래→위 줄 순서)를 두면 그 찍은 사진을 우리 사진으로 바꾼다.
/// </summary>
internal static class ManagerFace
{
    public static int Hits;
    private static Texture2D? _tex;
    private static DateTime _stamp;
    private static IntPtr _orig = IntPtr.Zero;

    private static string FilePath => Path.Combine(Bridge.Dir, "manager.raw");
    // 게임이 그림을 걸 때마다 디스크를 묻지 않게 1초 캐시
    private static bool _has;
    private static float _hasAt = -10f;
    public static bool HasPhoto
    {
        get
        {
            var now = Time.realtimeSinceStartup;
            if (now - _hasAt > 1f) { _hasAt = now; try { _has = File.Exists(FilePath); } catch { _has = false; } }
            return _has;
        }
    }

    public static void Install()
    {
        var flags = System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic;
        try
        {
            var get = AccessTools.Method(typeof(FM.UI.ManagerAppearance.ManagerCloseupShot), "GetManagerCloseupTexture");
            Plugin.H.Patch(get, postfix: new HarmonyMethod(typeof(ManagerFace).GetMethod(nameof(CloseupPostfix), flags)));
        }
        catch (Exception e) { Plugin.L.LogWarning("감독 사진 연결 실패(촬영): " + e.Message); }
        try
        {
            foreach (var m in AccessTools.GetDeclaredMethods(typeof(SI.Bindable.SIImage)).Where(m => m.Name == "SetImage"))
            {
                var ps = m.GetParameters();
                if (ps.Length < 1) continue;
                var t = ps[0].ParameterType;
                string? name = t == typeof(Texture2D) ? nameof(SetImagePrefix2D) : t == typeof(Texture) ? nameof(SetImagePrefixTex) : null;
                if (name is null) continue;
                Plugin.H.Patch(m, prefix: new HarmonyMethod(typeof(ManagerFace).GetMethod(name, flags)));
            }
        }
        catch (Exception e) { Plugin.L.LogWarning("감독 사진 연결 실패(표시): " + e.Message); }
        Plugin.L.LogInfo($"감독 사진 연결 준비 (사진 파일 {(HasPhoto ? "있음" : "없음")}: {FilePath})");
    }

    private static Texture2D? Photo()
    {
        try
        {
            if (!File.Exists(FilePath)) { _tex = null; return null; }
            var t = File.GetLastWriteTimeUtc(FilePath);
            if (_tex is not null && t == _stamp) return _tex;
            var bytes = File.ReadAllBytes(FilePath);
            int w = BitConverter.ToInt32(bytes, 0), h = BitConverter.ToInt32(bytes, 4);
            if (w <= 0 || h <= 0 || bytes.Length < 8 + w * h * 4) return _tex;
            var data = new byte[w * h * 4];
            Buffer.BlockCopy(bytes, 8, data, 0, data.Length);
            var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
            tex.LoadRawTextureData(data);
            tex.Apply(false, false);
            tex.hideFlags = HideFlags.HideAndDontSave;
            tex.name = "FaceStudioManager";
            _tex = tex;
            _stamp = t;
            Plugin.L.LogInfo($"감독 사진 불러옴 {w}x{h}");
            return _tex;
        }
        catch (Exception e)
        {
            Plugin.L.LogWarning("감독 사진 읽기 실패: " + e.Message);
            return _tex;
        }
    }

    public static int Shots;
    private static void CloseupPostfix(ref Texture2D __result)
    {
        Shots++;
        if (Shots <= 3) Plugin.L.LogInfo($"게임이 감독 사진을 찍음 ({Shots}번째)");
        // 사진이 나중에 생겨도 바꿀 수 있게, 게임이 찍은 원본은 항상 기억해 둔다.
        if (__result is not null && (_tex is null || __result.Pointer != _tex.Pointer)) _orig = __result.Pointer;
        var p = Photo();
        if (p is null) return;
        __result = p;
        Hits++;
    }

    private static int _closeupSize = -1;
    private static bool LooksLikeManagerShot(Texture2D t)
    {
        // 게임이 그림을 직접 거는 건 감독 사진뿐이다 (다른 사진은 'person_123' 같은 이름으로 불러온다).
        // 이름 없는 정사각형 + 감독 촬영 크기와 같으면 감독 사진으로 본다.
        try
        {
            if (_closeupSize < 0)
            {
                try { _closeupSize = FM.UI.ManagerAppearance.ManagerCloseupShot.ManagerCloseupTextureSize; } catch { _closeupSize = 0; }
                Plugin.L.LogInfo($"감독 촬영 크기: {_closeupSize}");
            }
            if (!string.IsNullOrEmpty(t.name)) return false;
            if (t.width != t.height) return false;
            return _closeupSize <= 0 ? t.width == 256 : t.width == _closeupSize;
        }
        catch { return false; }
    }

    private static void SetImagePrefix2D(ref Texture2D __0)
    {
        if (Collect.On && __0 is not null) Collect.Take(__0, "SetImage(Texture2D)");
        if (__0 is null || !HasPhoto) return;
        if (_tex is not null && __0.Pointer == _tex.Pointer) return;
        if (!(__0.Pointer == _orig || LooksLikeManagerShot(__0))) return;
        var p = Photo();
        if (p is null) return;
        _orig = __0.Pointer;
        __0 = p;
        if (++Hits <= 3) Plugin.L.LogInfo($"감독 사진 바꿔 끼움 ({Hits}번째)");
    }

    private static void SetImagePrefixTex(ref Texture __0)
    {
        if (Collect.On && __0 is not null) Collect.Take(__0, "SetImage(Texture)");
        if (__0 is null || _orig == IntPtr.Zero || __0.Pointer != _orig) return;
        var p = Photo();
        if (p is not null) { __0 = p; Hits++; }
    }
}


/// <summary>
/// 게임이 뉴젠 얼굴을 그리기 직전에 만드는 '외모 문자열'(인종·피부색·머리 등)을 UID와 짝지어 appearance.json에 모은다.
/// 앱이 이 값으로 AI 프롬프트에 그 사람의 실제 외모 설정을 넣는다.
/// </summary>
internal static class Appearance
{
    private static readonly Dictionary<string, string> Map = new();
    private static IntPtr _lastRef = IntPtr.Zero;
    private static string? _lastCode;
    private static int _lastFrame = -1;
    private static int _encodesInFrame;
    private static bool _dirty;
    private static float _nextFlush;
    public static int Count => Map.Count;
    private static string FilePath => Path.Combine(Bridge.Dir, "appearance.json");

    public static void Install()
    {
        try
        {
            // 0.8.1: 예전엔 같은 화면 갱신에 나온 외모를 다른 사람과 짝짓는 일이 있었다 → 한 번 비우고 다시 모은다
            var mark = Path.Combine(Bridge.Dir, "appearance.v2");
            if (!File.Exists(mark))
            {
                try { if (File.Exists(FilePath)) File.Delete(FilePath); } catch { }
                try { File.WriteAllText(mark, "1"); } catch { }
            }
            if (File.Exists(FilePath))
            {
                var old = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(FilePath));
                if (old is not null) foreach (var kv in old) Map[kv.Key] = kv.Value;
            }
        }
        catch { }
        var flags = System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic;
        try
        {
            var t = typeof(FM.UI.DatabaseObjectImageHelpers);
            var enc = AccessTools.Method(t, "EncodeNewgenAppearanceDescription");
            Plugin.H.Patch(enc, postfix: new HarmonyMethod(typeof(Appearance).GetMethod(nameof(EncodePost), flags)));
            foreach (var m in AccessTools.GetDeclaredMethods(t).Where(m => m.Name == "ConvertDynamicReferenceToAddressableID"))
            {
                var ps = m.GetParameters();
                if (ps.Length == 0 || ps[0].ParameterType != typeof(SI.Bindable.DynamicReference)) continue;
                Plugin.H.Patch(m, postfix: new HarmonyMethod(typeof(Appearance).GetMethod(nameof(ConvertPost), flags)));
            }
            Plugin.L.LogInfo($"외모 기록 준비 (지금까지 {Map.Count}명)");
        }
        catch (Exception e) { Plugin.L.LogWarning("외모 기록 연결 실패: " + e.Message); }
    }

    private static void EncodePost(SI.Bindable.DynamicReference __0, string __result)
    {
        try
        {
            var f = Time.frameCount;
            _encodesInFrame = f == _lastFrame ? _encodesInFrame + 1 : 1;
            _lastRef = __0 is null ? IntPtr.Zero : __0.Pointer;
            _lastCode = __result;
            _lastFrame = f;
        }
        catch { }
    }

    private static void ConvertPost(SI.Bindable.DynamicReference __0, string __result)
    {
        try
        {
            if (_lastCode is null || __result is null) return;
            string uid;
            if (__result.StartsWith("newgen_")) uid = __result.Substring(7);
            else return;
            var same = __0 is not null && __0.Pointer == _lastRef;
            // 같은 대상이 확실할 때만. 같은 화면 갱신이라도 얼굴이 여러 개 그려졌으면 누구 것인지 모르니 버린다
            if (!same && (Time.frameCount != _lastFrame || _encodesInFrame > 1)) return;
            if (!Map.TryGetValue(uid, out var cur) || cur != _lastCode)
            {
                Map[uid] = _lastCode;
                _dirty = true;
            }
            _lastCode = null;
        }
        catch { }
    }

    private static volatile bool _saving;
    public static void Tick(float now)
    {
        if (!_dirty || _saving || now < _nextFlush) return;
        _nextFlush = now + 10f;
        _dirty = false;
        // 게임 화면이 멈추지 않게: 복사본만 만들고 저장은 백그라운드에서
        var snap = new Dictionary<string, string>(Map);
        var path = FilePath;
        _saving = true;
        System.Threading.ThreadPool.QueueUserWorkItem(_ =>
        {
            try
            {
                var tmp = path + ".tmp";
                File.WriteAllText(tmp, JsonSerializer.Serialize(snap), new UTF8Encoding(false));
                File.Move(tmp, path, true);
            }
            catch (Exception e) { try { Plugin.L.LogWarning("외모 기록 저장 실패: " + e.Message); } catch { } }
            finally { _saving = false; }
        });
    }
}


/// <summary>
/// 연구용 '이미지 수집': 정해진 시간 동안 게임이 화면 그림 칸(SIImage)에 거는 그림을 모두 저장한다.
/// 클럽 정보 화면의 유니폼처럼, 게임이 직접 그린 그림을 앱이 가져다 쓸 수 있는지 찾으려고 쓴다.
/// 그림마다 raw(가로·세로 int32 + RGBA, 아래 줄부터)와 index.txt 한 줄. png 변환은 앱이 한다.
/// </summary>
internal static class Collect
{
    private static float _until;
    private static string _dir = "";
    private static readonly HashSet<IntPtr> Seen = new();
    public static int Count;
    public static bool On => Time.realtimeSinceStartup < _until;

    private static bool _patched;
    private static void EnsurePatched()
    {
        if (_patched) return;
        _patched = true;
        var flags = System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic;
        void P(Type t, string name, string patch, bool post = false)
        {
            foreach (var m in AccessTools.GetDeclaredMethods(t).Where(x => x.Name == name))
            {
                try
                {
                    var hm = new HarmonyMethod(typeof(Collect).GetMethod(patch, flags));
                    if (post) Plugin.H.Patch(m, postfix: hm); else Plugin.H.Patch(m, prefix: hm);
                }
                catch (Exception e) { Plugin.L.LogWarning($"수집 감시 실패 {t.Name}.{name}: {e.Message}"); }
            }
        }
        // FM27 화면은 UI Toolkit: 그림은 Image.image / Image.sprite 로도 걸린다
        P(typeof(UnityEngine.UIElements.Image), "set_image", nameof(ImagePrefix));
        P(typeof(UnityEngine.UIElements.Image), "set_sprite", nameof(SpritePrefix));
        // 유니폼 그림 주소(리소스 ID)를 만드는 곳
        P(typeof(FM.UI.DatabaseObjectImageHelpers), "GetKit2DResourceID", nameof(KitIdPost), true);
        P(typeof(FM.UI.DatabaseObjectImageHelpers), "GetLicensedKit2DResourceID", nameof(KitIdPost), true);
    }

    private static void ImagePrefix(Texture __0) { if (On && __0 is not null) Take(__0, "UI.Image.image"); }
    private static void SpritePrefix(Sprite __0)
    {
        if (!On || __0 is null) return;
        try { var t = __0.texture; if (t is not null) Take(t, "UI.Image.sprite:" + (__0.name ?? "")); } catch { }
    }
    private static void KitIdPost(string __result)
    {
        if (!On || string.IsNullOrEmpty(__result)) return;
        try { File.AppendAllText(Path.Combine(_dir, "index.txt"), $"KIT-ID\t{__result}\n", new UTF8Encoding(false)); } catch { }
    }

    public static string Start(int seconds)
    {
        EnsurePatched();
        _dir = Path.Combine(Bridge.DiagDir, $"images-{DateTime.Now:yyyyMMdd-HHmmss}");
        Directory.CreateDirectory(_dir);
        File.WriteAllText(Path.Combine(_dir, "index.txt"), $"# FM Face Studio 이미지 수집, plugin {Plugin.Version}, {DateTime.Now:yyyy-MM-dd HH:mm:ss}\n", new UTF8Encoding(false));
        Seen.Clear();
        Count = 0;
        _until = Time.realtimeSinceStartup + Math.Clamp(seconds, 10, 600);
        return $"이미지 수집 시작 ({Math.Clamp(seconds, 10, 600)}초). 클럽 정보 → 개요(유니폼) 같은 화면을 열어 주세요.";
    }

    public static string Stop()
    {
        _until = 0;
        return $"이미지 수집 끝: {Count}장";
    }

    public static void Tick(float now) { }

    /// <summary>GPU 그림을 읽어 raw 파일(가로·세로 int32 + RGBA, 아래 줄부터)로 저장.</summary>
    public static void SaveRaw(Texture tex, string file)
    {
        int w = tex.width, h = tex.height;
        var rt = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGB32);
        var prev = RenderTexture.active;
        Graphics.Blit(tex, rt);
        RenderTexture.active = rt;
        var t2 = new Texture2D(w, h, TextureFormat.RGBA32, false);
        t2.ReadPixels(new Rect(0, 0, w, h), 0, 0);
        t2.Apply();
        RenderTexture.active = prev;
        RenderTexture.ReleaseTemporary(rt);
        byte[] data = t2.GetRawTextureData();
        UnityEngine.Object.Destroy(t2);
        var tmp = file + ".part";
        using (var fs = File.Create(tmp))
        {
            fs.Write(BitConverter.GetBytes(w));
            fs.Write(BitConverter.GetBytes(h));
            fs.Write(data);
        }
        File.Move(tmp, file, true);
    }

    public static void Take(Texture tex, string via)
    {
        try
        {
            if (Count >= 300) return;
            var ptr = tex.Pointer;
            if (!Seen.Add(ptr)) return;
            int w = tex.width, h = tex.height;
            if (w < 48 || h < 48 || w > 2048 || h > 2048) return;
            Count++;
            SaveRaw(tex, Path.Combine(_dir, $"{Count:000}.raw"));
            var kind = tex.GetIl2CppType().Name;
            File.AppendAllText(Path.Combine(_dir, "index.txt"),
                $"{Count:000}\t{w}x{h}\t{kind}\t{(tex.name ?? "").Replace('\t', ' ')}\t{via}\n", new UTF8Encoding(false));
        }
        catch (Exception e)
        {
            try { Plugin.L.LogWarning("이미지 수집 실패: " + e.Message); } catch { }
        }
    }
}


/// <summary>
/// 게임이 클럽 화면에 거는 유니폼 그림(이름이 "marine home" 같은 1024px 그림)을 클럽 번호와 짝지어 저장한다.
/// 짝: 그림을 걸기 직전에 게임이 만드는 주소 kit2d_<클럽번호>_<home|away|third>.
/// 저장: kits/<클럽번호>_<종류>.raw + kits/index.json. png 변환은 앱이 한다.
/// </summary>
internal static class Kits
{
    private static readonly Dictionary<string, (string club, float at)> Pending = new();
    // 공식 유니폼 그림은 이름이 없다("Local Asset Texture") → 주소를 부른 직후 '바로 다음' 그림 하나만 그 유니폼으로 본다
    private static (string club, string kind, float at, long seq)? _last;
    private static long _seq;
    private static readonly Dictionary<string, string> Saved = new();   // "682_home" -> 그림 이름
    private static readonly HashSet<IntPtr> Done = new();
    private static string KitDir => Path.Combine(Bridge.Dir, "kits");
    public static int Count => Saved.Count;

    public static void Install()
    {
        try
        {
            Directory.CreateDirectory(KitDir);
            var idx = Path.Combine(KitDir, "index.json");
            if (File.Exists(idx))
                foreach (var kv in JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(idx)) ?? new())
                    Saved[kv.Key] = kv.Value;
        }
        catch (Exception e) { Plugin.L.LogWarning("유니폼 기록 읽기 실패: " + e.Message); }
        var flags = System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic;
        void P(Type t, string name, string patch, bool post)
        {
            foreach (var m in AccessTools.GetDeclaredMethods(t).Where(x => x.Name == name))
            {
                try
                {
                    var hm = new HarmonyMethod(typeof(Kits).GetMethod(patch, flags));
                    if (post) Plugin.H.Patch(m, postfix: hm); else Plugin.H.Patch(m, prefix: hm);
                }
                catch (Exception e) { Plugin.L.LogWarning($"유니폼 감시 실패 {t.Name}.{name}: {e.Message}"); }
            }
        }
        P(typeof(FM.UI.DatabaseObjectImageHelpers), "GetKit2DResourceID", nameof(IdPost), true);
        P(typeof(FM.UI.DatabaseObjectImageHelpers), "GetLicensedKit2DResourceID", nameof(IdPost), true);
        P(typeof(UnityEngine.UIElements.Image), "set_image", nameof(ImagePrefix), false);
    }


    private static void IdPost(string __result)
    {
        try
        {
            if (string.IsNullOrEmpty(__result)) return;
            var parts = __result.Split('_');      // kit2d_<클럽번호>_<home|away|third>
            if (parts.Length != 3 || parts[0] != "kit2d" || parts[1].Length == 0 || !parts[1].All(char.IsDigit)) return;
            if (parts[2] is "home" or "away" or "third")
            {
                Pending[parts[2]] = (parts[1], Time.realtimeSinceStartup);
                _last = (parts[1], parts[2], Time.realtimeSinceStartup, _seq);
            }
        }
        catch { }
    }

    private static void ImagePrefix(Texture __0)
    {
        try
        {
            if (__0 is null) return;
            var seq = ++_seq;
            var last = _last;
            _last = null;                                   // 주소 다음 '첫 그림'만 본다
            var ptr = __0.Pointer;
            if (Done.Contains(ptr)) return;
            var nm0 = __0.name ?? "";
            if (nm0.StartsWith("NewgenPortraitTexture-")) { Done.Add(ptr); NewgenFaces.Save(__0, nm0.Substring(22)); return; }
            if (__0.width < 256 || __0.height < 256 || __0.width > 2048) return;
            var name = __0.name ?? "";
            string? kind = name.EndsWith(" home") ? "home" : name.EndsWith(" away") ? "away" : name.EndsWith(" third") ? "third" : null;
            string club;
            if (kind is not null)
            {
                // 유니폼 팩 그림 (이름에 home/away/third)
                if (!Pending.TryGetValue(kind, out var p) || Time.realtimeSinceStartup - p.at > 5f) return;
                club = p.club;
            }
            else
            {
                // 공식 유니폼 그림: 이름 없음, 정사각형, 주소 바로 다음, 1초 안
                if (last is null || last.Value.seq != seq - 1 || Time.realtimeSinceStartup - last.Value.at > 1f) return;
                if (__0.width != __0.height || name.StartsWith("NewgenPortrait") || name.StartsWith("FaceStudio")) return;
                club = last.Value.club;
                kind = last.Value.kind;
            }
            Done.Add(ptr);
            var key = club + "_" + kind;
            var file = Path.Combine(KitDir, key + ".raw");
            if (Saved.TryGetValue(key, out var old) && old == name && (File.Exists(file) || File.Exists(Path.Combine(KitDir, key + ".png")))) return;
            Collect.SaveRaw(__0, file);
            Saved[key] = name;
            Bridge.WriteJson(Path.Combine(KitDir, "index.json"), Saved);
            Plugin.L.LogInfo($"유니폼 저장: {key} ({name})");
        }
        catch (Exception e) { try { Plugin.L.LogWarning("유니폼 저장 실패: " + e.Message); } catch { } }
    }
}

/// <summary>
/// 게임이 그린 뉴젠 3D 얼굴(텍스처 이름 NewgenPortraitTexture-UID)을 사람별로 저장한다.
/// 앱이 사진 없는 뉴젠을 AI로 그릴 때 참고 사진으로 쓴다.
/// </summary>
internal static class NewgenFaces
{
    private static readonly HashSet<string> Seen = new();
    private static string Dir => Path.Combine(Bridge.Dir, "newgen");

    public static void Save(Texture tex, string uid)
    {
        try
        {
            if (uid.Length == 0 || !uid.All(char.IsDigit) || Seen.Contains(uid)) return;
            if (tex.width < 64 || tex.width > 1024) return;
            Seen.Add(uid);
            Directory.CreateDirectory(Dir);
            Collect.SaveRaw(tex, Path.Combine(Dir, uid + ".raw"));
        }
        catch (Exception e) { try { Plugin.L.LogWarning("뉴젠 얼굴 저장 실패: " + e.Message); } catch { } }
    }
}
