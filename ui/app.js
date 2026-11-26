"use strict";
/* FM27 Face Studio — 화면 로직 */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ico = (n, cls = "i") => `<svg class="${cls}"><use href="#i-${n}"/></svg>`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const GROUPS = { free_web: "무료 · 웹에서 직접", free_auto: "무료 · 자동", sub: "구독", api: "API 키 · 쓴 만큼 요금" };
const TAG = { free_web: ["free", "무료"], free_auto: ["free", "무료"], sub: ["sub", "구독"], api: ["paid", "유료"] };
const HOWTO = {
  web_gemini: ["'사이트 열기'를 누르면 프롬프트가 복사되고 제미나이가 열려요.", "참고 사진을 켰으면 사진 파일이 있는 폴더가 같이 열려요. 사진을 제미나이 입력창에 끌어다 놓아요.", "입력창에 Ctrl+V로 프롬프트를 붙여넣고 보내요.", "완성된 사진을 우클릭 → 이미지 복사 후, 이 프로그램에서 Ctrl+V."],
  web_chatgpt: ["'사이트 열기'를 누르면 프롬프트가 복사되고 챗GPT가 열려요.", "참고 사진을 켰으면 사진 파일을 입력창에 끌어다 놓아요.", "Ctrl+V로 프롬프트를 붙여넣고 보내요.", "완성된 사진을 복사해서 이 프로그램에서 Ctrl+V."],
  web_grok: ["'사이트 열기'를 누르면 프롬프트가 복사되고 그록 Imagine이 열려요.", "참고 사진을 켰으면 사진 파일을 끌어다 놓아요.", "Ctrl+V로 프롬프트를 붙여넣고 만들어요.", "완성된 사진을 복사해서 이 프로그램에서 Ctrl+V."],
  cloudflare: ["dash.cloudflare.com 에서 무료 계정을 만들어요.", "오른쪽 위 계정 메뉴의 Account ID를 복사해 아래 '계정 ID'에 넣어요.", "내 프로필 → API 토큰 → 토큰 만들기 → 'Workers AI' 템플릿으로 만든 토큰을 '토큰'에 넣어요.", "하루 무료 사용량 안에서 버튼 하나로 생성돼요. 참고 사진은 못 보내요."],
  codex: ["ChatGPT 유료 구독(Plus 이상)이 필요해요.", "Node.js 설치 후 명령 프롬프트에서: npm i -g @openai/codex", "codex login 으로 ChatGPT 계정 로그인.", "프로그램을 다시 켜면 '설치됨'으로 바뀌어요. 한 장에 30초~1분 걸려요."],
  gemini: ["aistudio.google.com/apikey 에서 키를 만들어요.", "이미지 생성은 결제를 등록한 계정에서만 돼요 (무료 키는 오류).", "키를 아래에 넣어요."],
  openai: ["platform.openai.com/api-keys 에서 키를 만들어요.", "크레딧 충전이 필요해요.", "키를 아래에 넣어요."],
  xai: ["console.x.ai 에서 키를 만들어요.", "크레딧 충전이 필요해요.", "키를 아래에 넣어요. 참고 사진은 못 보내요."],
};
const KEY_URL = { gemini: "https://aistudio.google.com/apikey", openai: "https://platform.openai.com/api-keys", xai: "https://console.x.ai/", cloudflare: "https://dash.cloudflare.com/" };

const S = {
  kind: "player",
  people: { loaded: false, count: 0, my_clubs: [] },
  results: [],
  selUid: null,
  photo: null,            // {img, w, h, box:[cx,cy,side], auto, nobg, isOriginal}
  queue: [],
  applied: [],
  aSel: new Set(),
  settings: {},
  ai: [],
  styles: {},
  defaultPrompt: "",
  promptDirty: false,
  deco: { caption: false, text: "", style: "gold", rounded: false, radius: 14, border: false },
  decoTextDirty: false,
};

/* ------------------------------------------------------------------ API */
let API = null;
function ready() {
  return new Promise((res) => {
    if (window.pywebview && window.pywebview.api) return res(window.pywebview.api);
    window.addEventListener("pywebviewready", () => res(window.pywebview.api));
    setTimeout(() => {   // 개발용: 브라우저에서 dev_server.py로 열었을 때
      if (!window.pywebview && location.protocol.startsWith("http")) {
        window.pywebview = { api: new Proxy({}, { get: (_, n) => n === "then" ? undefined : (...a) =>
          fetch("/api/" + n, { method: "POST", body: JSON.stringify(a) }).then((r) => r.json()) }) };
        res(window.pywebview.api);
      }
    }, 400);
  });
}
async function call(name, ...args) {
  try {
    const r = await API[name](...args);
    if (r && typeof r === "object" && !Array.isArray(r) && r.error) {
      if (r.error === "need_key") return r;
      toast(r.error, "err");
      return null;
    }
    return r;
  } catch (e) {
    toast("오류: " + (e && e.message ? e.message : e), "err");
    return null;
  }
}

/* ------------------------------------------------------------------ 공통 UI */
function toast(msg, kind = "info", ms = 3800) {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.innerHTML = ico(kind === "ok" ? "check" : kind === "err" ? "alert" : "info") + `<div>${esc(msg)}</div>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.transition = ".3s"; t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, kind === "err" ? ms + 3000 : ms);
}
function confirmBox(title, body, yes = "확인", danger = false) {
  return new Promise((res) => {
    $("#cTitle").textContent = title;
    $("#cBody").textContent = body;
    const y = $("#cYes"), n = $("#cNo");
    y.textContent = yes;
    y.className = "btn " + (danger ? "danger" : "primary");
    const close = (v) => { $("#mConfirm").classList.remove("on"); y.onclick = n.onclick = null; res(v); };
    y.onclick = () => close(true);
    n.onclick = () => close(false);
    $("#mConfirm").classList.add("on");
  });
}
let progTimer = null;
function busy(on, text = "처리 중…", sub = "") {
  $("#busy").classList.toggle("on", on);
  $("#busyText").textContent = text;
  $("#busySub").textContent = sub;
  clearInterval(progTimer);
  if (on) progTimer = setInterval(async () => {
    const p = await API.progress();
    if (p && p.task) {
      $("#busyText").textContent = p.task;
      $("#busySub").textContent = p.total ? `${Math.floor(p.done / p.total * 100)}% · ${(p.done / 1048576).toFixed(0)} / ${(p.total / 1048576).toFixed(0)} MB` : `${(p.done / 1048576).toFixed(0)} MB`;
    }
  }, 500);
}
function hue(s) { let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function initials(name) {
  const p = String(name || "?").trim().split(/\s+/);
  return ((p[0] || "?")[0] + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
}
function avatar(p) {
  if (p.face) return `<div class="av"><img src="${p.face}"></div>`;
  const h = hue(p.name || p.uid);
  return `<div class="av" style="background:linear-gradient(135deg,hsl(${h} 55% 42%),hsl(${(h + 40) % 360} 60% 30%))">${esc(initials(p.name))}</div>`;
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; } catch (e) { /* 아래 방식으로 */ }
  const ta = document.createElement("textarea");
  ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

/* ------------------------------------------------------------------ 탭 */
$$(".tab").forEach((b) => b.onclick = () => {
  $$(".tab").forEach((x) => x.classList.toggle("on", x === b));
  $$(".page").forEach((p) => p.classList.toggle("on", p.id === b.dataset.page));
  if (b.dataset.page === "pageApplied") loadApplied();
  else requestAnimationFrame(drawStage);
});

/* ------------------------------------------------------------------ 1. 첫 화면: 선수 카드 */
S.filter = "all"; S.squad = ""; S.bItems = []; S.bTotal = 0; S.bEmpty = true; S.bIndex = {}; S.peopleVer = -1; S.indexCount = -1;
async function pickSave() {
  toast("세이브를 고르면 읽는 데 시간이 걸릴 수 있어요…", "info", 4000);
  const r = await call("pick_save");
  if (r) afterSave(r);
}
async function readSaveNow(which) {
  const r = await call("read_save_now", which);
  if (!r) return;
  toast(`세이브를 읽고 있어요: ${(r.path || "").split(/[\\/]/).pop()}\n처음엔 수십 초 걸릴 수 있어요.`, "info", 5000);
  pollStatus();
}
async function reloadSave() { return readSaveNow("reload"); }
function afterSave(r) {
  S.people = r;
  if (r.loaded) toast(`인물 ${r.count.toLocaleString()}명을 불러왔어요${r.cached ? " (저장된 목록 사용)" : r.seconds ? ` (${r.seconds}초)` : ""}.`, "ok");
  doSearch(true);
  pollStatus();
}
let bLoading = false;
async function doSearch(reset = true) {
  if (bLoading && !reset) return;
  bLoading = true;
  const n = $("#qName").value.trim(), t = $("#qTeam").value.trim();
  const r = await call("browse", n, t, S.kind, S.filter, 0, 50, S.kind === "player" ? S.squad : "");
  bLoading = false;
  if (!r) return;
  S.bTotal = r.total; S.bEmpty = r.empty_query; S.bIndex = r.index;
  S.bItems = r.items; S.bMax = r.max || 50;
  renderBrowse(reset);
}
function cardHtml(p, i) {
  const tag = p.face_state === "ours" ? '<span class="tag ours">내가 넣은 사진</span>' : p.face_state === "none" ? '<span class="tag none">사진 없음</span>' : `<span class="tag">${esc(p.pack)}</span>`;
  const tag2 = p.me ? '<span class="tag2">내 감독</span>' : p.newgen ? '<span class="tag2" style="background:rgba(31,209,165,.85);color:#03261c">뉴젠</span>' : "";
  const sq = p.squad && p.squad !== "1군" ? ` · ${esc(p.squad)}` : "";
  return `<div class="pcard2" data-i="${i}">${tag}${tag2}
    <div class="ph2">${p.face ? `<img src="${p.face}" loading="lazy">` : "사진 없음"}</div>
    <div class="nm">${esc(p.name)}</div>
    <div class="sub">${esc(p.club || "무소속")}${p.alt ? ` <span class="alt">(${esc(p.alt)})</span>` : ""}${sq}${p.age ? " · " + esc(p.age) + "세" : ""}${p.job && !p.me ? " · " + esc(p.job) : ""}</div></div>`;
}
function renderBrowse(reset = true) {
  const g = $("#bgrid"), more = $("#bmore"), sv = (ST && ST.save) || {};
  const loaded = S.people.loaded || (sv.loaded);
  const reading = sv.reading && sv.reading.active;
  const idxTxt = S.bIndex && S.bIndex.building ? " · 기존 사진 찾는 중…" : S.bIndex && S.bIndex.count ? ` · 기존 사진 ${S.bIndex.count.toLocaleString()}장` : "";
  $("#bStat").textContent = loaded ? `${S.bEmpty && S.kind !== "manager" ? "내 팀 " : ""}${S.bTotal.toLocaleString()}명${idxTxt}` : "";
  if (!loaded) {
    g.innerHTML = `<div class="empty" style="grid-column:1/-1;padding:70px 20px">${reading
      ? `<div><div class="spin"></div><b style="color:var(--text);font-size:14px">세이브를 읽는 중이에요</b><br>${esc((sv.reading.path || "").split(/[\\\\/]/).pop())}<br>처음엔 수십 초 걸릴 수 있어요.</div>`
      : `<div>${ico("folder")}<br><b style="color:var(--text);font-size:14px">불러온 세이브가 없어요</b><br>버튼을 눌러야 세이브를 읽어요. 시작할 때는 자동으로 읽지 않아요.<br><br><button class="btn primary" id="btnReadCur">게임의 최근 세이브 읽기</button>&nbsp;<button class="btn" id="btnPickSave2">세이브 직접 고르기</button>&nbsp;<button class="btn" id="btnManual2">UID로 직접 편집</button></div>`}</div>`;
    more.innerHTML = "";
    const b0 = $("#btnReadCur"), b1 = $("#btnPickSave2"), b2 = $("#btnManual2");
    if (b0) b0.onclick = () => readSaveNow("current");
    if (b1) b1.onclick = pickSave;
    if (b2) b2.onclick = () => openManual();
    return;
  }
  if (!S.bItems.length) {
    g.innerHTML = `<div class="empty" style="grid-column:1/-1;padding:70px 20px"><div>${ico(S.kind === "support" ? "users" : "search")}<br>${S.kind === "support"
      ? "세이브 파일에는 지원 스태프(개인 비서·언론 담당자·선수 연락 담당자)가 없어요.<br>게임 프로필의 고유번호로 <b>'UID로 직접 편집'</b>에서 넣어 주세요. r-는 자동으로 붙어요."
      : S.kind === "manager" ? "세이브에서 내 감독을 찾지 못했어요. 세이브를 다시 읽어 보세요."
      : S.bEmpty ? "이름이나 팀으로 검색해 보세요." : "조건에 맞는 인물이 없어요."}</div></div>`;
    more.innerHTML = "";
    return;
  }
  g.innerHTML = S.bItems.map(cardHtml).join("");
  $$(".pcard2", g).forEach((c) => c.onclick = () => {
    c.classList.add("picked");
    setTimeout(() => { c.classList.remove("picked"); pickPerson(S.bItems[+c.dataset.i], +c.dataset.i); }, 130);
  });
  more.innerHTML = S.bTotal > S.bItems.length ? `<div class="capnote">최대 ${S.bMax}명까지만 보여요 (전체 ${S.bTotal.toLocaleString()}명). 이름이나 팀을 더 입력해 주세요.</div>` : "";
  if (S.kind === "manager" && S.bItems.length) more.innerHTML = `<div class="capnote">내 감독 사진은 플러그인이 있어야 게임에 반영돼요. (감독 사진은 config.xml로는 안 바뀌어요)</div>`;
  if (reset) $("#bwrap").scrollTop = 0;
}
$$("#sqChips .chip").forEach((c) => c.onclick = () => {
  S.squad = c.dataset.s;
  $$("#sqChips .chip").forEach((x) => x.classList.toggle("on", x === c));
  doSearch(true);
});
let qTimer;
["#qName", "#qTeam"].forEach((s) => $(s).addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(() => doSearch(true), 200); }));
$$("#fChips .chip").forEach((c) => c.onclick = () => {
  S.filter = c.dataset.f;
  $$("#fChips .chip").forEach((x) => x.classList.toggle("on", x === c));
  doSearch(true);
});
$("#btnMyTeam").onclick = () => {
  const clubs = S.people.my_clubs || [];
  if (!clubs.length) { $("#qTeam").value = ""; doSearch(true); return; }
  const cur = $("#qTeam").value.trim();
  const i = clubs.indexOf(cur);
  $("#qTeam").value = i >= 0 && clubs.length > 1 ? clubs[(i + 1) % clubs.length] : clubs[0];
  doSearch(true);
};
$$("#kindSeg button").forEach((b) => b.onclick = () => { setKind(b.dataset.kind); doSearch(true); });

/* 화면 전환 */
function animate(el, cls) {
  el.classList.remove("anim-in-r", "anim-in-l", "anim-swap");
  void el.offsetWidth;
  el.classList.add(cls);
  el.addEventListener("animationend", () => el.classList.remove(cls), { once: true });
}
function showView(v) {
  const was = $("#viewEdit").classList.contains("on") ? "edit" : "browse";
  $("#viewBrowse").classList.toggle("on", v === "browse");
  $("#viewEdit").classList.toggle("on", v === "edit");
  if (v === "edit") { if (was !== "edit") animate($("#viewEdit"), "anim-in-r"); requestAnimationFrame(drawStage); }
  else if (was === "edit") animate($("#viewBrowse"), "anim-in-l");
}
function inEdit() { return $("#viewEdit").classList.contains("on") && $("#pageMake").classList.contains("on"); }
async function goBack() {
  if (!inEdit()) return;
  showView("browse");
  await doSearch(true);
  const i = S.bItems.findIndex((p) => p.uid === S.selUid);
  const c = i >= 0 ? $(`.pcard2[data-i="${i}"]`) : null;
  if (c) { c.scrollIntoView({ block: "nearest" }); c.classList.add("flash"); setTimeout(() => c.classList.remove("flash"), 900); }
}
$("#btnBack").onclick = goBack;
function updatePN() {
  const i = S.curIdx ?? -1, n = S.bItems.length;
  const show = i >= 0 && n > 1 && S.bItems[i] && S.bItems[i].uid === S.selUid;
  $(".pn").style.visibility = show ? "visible" : "hidden";
  if (!show) return;
  $("#pnCount").textContent = `${i + 1} / ${n}`;
  $("#btnPrev").disabled = i <= 0;
  $("#btnNext").disabled = i >= n - 1;
}
async function stepPerson(d) {
  const i = (S.curIdx ?? -1) + d;
  if (!inEdit() || i < 0 || i >= S.bItems.length) return;
  animate($("#viewEdit"), "anim-swap");
  await pickPerson(S.bItems[i], i);
}
$("#btnPrev").onclick = () => stepPerson(-1);
$("#btnNext").onclick = () => stepPerson(1);
function openManual() {
  S.selUid = null; S.curIdx = -1;
  fillPerson({ kind: S.kind === "manager" ? "staff" : S.kind, me: S.kind === "manager", newgen: S.kind === "support" || S.kind === "manager" });
  if (S.kind === "support") $("#fUid").value = "r-";
  resetEditor();
  showCurrent(null);
  showView("edit");
  S.promptDirty = false; autoPrompt();
  $("#fUid").focus();
}
$("#btnManual").onclick = openManual;
function resetEditor() {
  S.photo = null;
  ctx.clearRect(0, 0, cv.width, cv.height);
  $("#drop").style.display = "";
  ["#btnAuto", "#btnNobg", "#zoom"].forEach((s) => $(s).disabled = true);
  $("#btnRevert").disabled = true;
  $("#pvImg").hidden = true; $("#pvBox .ph0").style.display = "";
  $("#zoomTxt").textContent = "-";
}
function showCurrent(r) {
  const box = $("#curFace");
  if (r && r.face) {
    box.innerHTML = `<img src="${r.face}">`;
    $("#curFrom").textContent = "지금 쓰이는 사진 · " + (r.ours ? "내가 넣은 사진" : r.pack);
    $("#btnUseCur").hidden = false;
  } else {
    box.innerHTML = ico("users");
    $("#curFrom").textContent = r ? "지금은 사진이 없어요 (게임 기본 얼굴)" : "";
    $("#btnUseCur").hidden = true;
  }
  const lk = $("#curLook");
  lk.hidden = !(r && r.look);
  if (r && r.look) lk.textContent = "게임 외모 기록 있음 · " + r.look;
  if (S.selUid == null) updatePN();
}
$("#btnUseCur").onclick = async () => {
  const uid = $("#fUid").value.trim();
  if (!uid) return;
  busy(true, "사진 불러오는 중…");
  const r = await call("load_existing", uid);
  busy(false);
  if (r) setPhoto(r);
};

function setKind(k) {
  S.kind = k;
  $$("#kindSeg button").forEach((x) => x.classList.toggle("on", x.dataset.kind === k));
  $("#sqRow").hidden = k !== "player";
  $("#mgrOutfit").hidden = k !== "manager";
}
function person() {
  return {
    uid: $("#fUid").value.trim(), name: $("#fName").value.trim(), club: $("#fClub").value.trim(),
    age: $("#fAge").value.trim(), nationality: $("#fNat").value.trim(),
    kind: S.kind === "manager" ? "staff" : S.kind, me: S.kind === "manager", newgen: $("#fNewgen").checked,
  };
}
function fillPerson(p) {
  $("#fUid").value = p.uid || ""; $("#fName").value = p.name || ""; $("#fClub").value = p.club || "";
  $("#fAge").value = p.age || ""; $("#fNat").value = p.nationality || ""; $("#fNewgen").checked = !!p.newgen;
  if (p.me) setKind("manager"); else if (p.kind) setKind(p.kind);
  $("#fClubHint").value = ((S.settings.club_hints || {})[p.club || ""]) || "";
  S.decoTextDirty = false;
  syncDecoText();
  updateCard();
}
async function pickPerson(p, idx) {
  S.selUid = p.uid;
  S.curIdx = typeof idx === "number" ? idx : -1;
  fillPerson(p);
  showView("edit");
  updatePN();
  S.promptDirty = false;
  const cur = await call("current_face", p.uid);
  showCurrent(cur || { face: "" });
  if (cur && cur.face) {
    busy(true, "지금 사진 불러오는 중…");
    const r = await call("load_existing", p.uid);
    busy(false);
    if (r) await setPhoto(r);
  } else {
    resetEditor();
  }
  autoPrompt();
}
$("#btnClear").onclick = () => { S.selUid = null; fillPerson({ kind: S.kind, newgen: S.kind === "support" }); showCurrent(null); S.promptDirty = false; autoPrompt(); };
["#fClub", "#fAge", "#fNat"].forEach((s) => $(s).addEventListener("input", () => { updateCard(); autoPromptSoon(); }));
$("#fName").addEventListener("input", () => { syncDecoText(); updateCard(); autoPromptSoon(); });
$("#fNewgen").onchange = updateCard;
$("#fUid").addEventListener("input", async () => {
  const raw = $("#fUid").value;
  const cleaned = raw.replace(/^\s*[rR]\s*-\s*/, "r-").replace(/[^0-9r-]/g, "");
  if (cleaned !== raw) $("#fUid").value = cleaned;
  if (S.selUid && cleaned.replace(/^r-/, "") !== S.selUid) { S.selUid = null; }
  if (/^r-/.test(cleaned)) $("#fNewgen").checked = true;
  else if (!S.selUid && cleaned.length >= 10) $("#fNewgen").checked = !!(await call("guess_newgen", cleaned));
  updateCard();
});
function updateCard() {
  const p = person();
  $("#whoName").textContent = p.name || "이름 없음";
  $("#crumbName").textContent = p.name || (p.uid ? p.uid : "새 인물");
  $("#whoSub").textContent = [p.club || "소속 없음", p.age ? p.age + "세" : ""].filter(Boolean).join(" · ");
  $("#pvName").textContent = p.name || "이름 없음";
  $("#pvSub").textContent = [p.club || "소속 없음", p.age ? p.age + "세" : ""].filter(Boolean).join(" · ");
  const uid = p.uid.replace(/^r-/, "");
  $("#whoTags").innerHTML = $("#pvTags").innerHTML = (uid ? `<span class="badge uid">${esc(uid)}</span>` : "") +
    (p.newgen ? '<span class="badge ng">뉴젠</span>' : "") +
    `<span class="badge face">${({ player: "선수", staff: "스태프", support: "지원 스태프", manager: "내 감독" })[S.kind]}</span>`;
}

/* ------------------------------------------------------------------ 2. 편집기 (틀 고정, 사진 이동) */
const cv = $("#cv"), ctx = cv.getContext("2d");
let view = { s: 1, fx: 0, fy: 0, F: 0 };

function setPhoto(payload, keepBox = false) {
  return new Promise((res) => {
    const img = new Image();
    img.onload = () => {
      const old = S.photo;
      S.photo = {
        img, w: payload.w, h: payload.h, nobg: payload.nobg,
        isOriginal: payload.is_original ?? (old ? old.isOriginal : true),
        box: keepBox && old ? old.box : payload.box, auto: payload.box || (old && old.auto),
      };
      $("#drop").style.display = "none";
      ["#btnAuto", "#btnNobg", "#zoom"].forEach((s) => $(s).disabled = false);
      $("#btnRevert").disabled = S.photo.isOriginal;
      $("#btnNobg").classList.toggle("on", !!S.photo.nobg);
      $("#pvBox").classList.toggle("checker", !!S.photo.nobg);
      S.photo.box = clampBox(S.photo.box);
      syncZoom(); drawStage(); res();
      if (!S.promptDirty) autoPrompt();
    };
    img.src = payload.url;
  });
}
function clampBox([cx, cy, side]) {
  const { w, h } = S.photo;
  side = Math.max(16, Math.min(side, Math.min(w, h)));
  cx = Math.min(Math.max(cx, side / 2), w - side / 2);
  cy = Math.min(Math.max(cy, side / 2), h - side / 2);
  return [cx, cy, side];
}
function framePath(x, y, d) {
  const r = S.deco.rounded ? d * S.deco.radius / 100 : 0;
  ctx.beginPath();
  if (r > 0 && ctx.roundRect) ctx.roundRect(x, y, d, d, r); else ctx.rect(x, y, d, d);
}
function drawStage() {
  const st = $("#stage"), dpr = window.devicePixelRatio || 1;
  const W = st.clientWidth, H = st.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const P = S.photo;
  if (!P) return;
  const F = Math.min(W, H) - 48, fx = (W - F) / 2, fy = (H - F) / 2;
  const [cx, cy, side] = P.box, s = F / side;
  view = { s, fx, fy, F };
  const ox = fx - (cx - side / 2) * s, oy = fy - (cy - side / 2) * s;
  if (P.nobg) {   // 투명 표시용 체크무늬 (틀 안)
    ctx.save(); framePath(fx, fy, F); ctx.clip();
    const c = 12;
    for (let y = 0; y < F; y += c) for (let x = 0; x < F; x += c) {
      ctx.fillStyle = ((x + y) / c) % 2 ? "#2c3653" : "#3a4566"; ctx.fillRect(fx + x, fy + y, c, c);
    }
    ctx.restore();
  }
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(P.img, ox, oy, P.w * s, P.h * s);
  // 틀 바깥 어둡게
  ctx.save();
  ctx.fillStyle = "rgba(5,8,18,.7)";
  ctx.beginPath(); ctx.rect(0, 0, W, H);
  const r = S.deco.rounded ? F * S.deco.radius / 100 : 0;
  if (r > 0 && ctx.roundRect) ctx.roundRect(fx, fy, F, F, r); else ctx.rect(fx, fy, F, F);
  ctx.fill("evenodd");
  // 삼등분 선
  ctx.save(); framePath(fx, fy, F); ctx.clip();
  ctx.strokeStyle = "rgba(255,255,255,.22)"; ctx.lineWidth = 1; ctx.setLineDash([4, 5]);
  for (const k of [1, 2]) {
    ctx.beginPath(); ctx.moveTo(fx + F * k / 3, fy); ctx.lineTo(fx + F * k / 3, fy + F); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(fx, fy + F * k / 3); ctx.lineTo(fx + F, fy + F * k / 3); ctx.stroke();
  }
  ctx.restore();
  ctx.setLineDash([]);
  const g = ctx.createLinearGradient(fx, fy, fx + F, fy + F);
  g.addColorStop(0, "#9a85ff"); g.addColorStop(1, "#1fd1a5");
  ctx.strokeStyle = g; ctx.lineWidth = 2.5; framePath(fx, fy, F); ctx.stroke();
  ctx.restore();
  requestPreview();
}
// 오른쪽 미리보기: 꾸미기까지 적용된 실제 결과 (파이썬이 그림)
let pvBusy = false, pvAgain = false;
async function requestPreview() {
  if (!S.photo) return;
  if (pvBusy) { pvAgain = true; return; }
  pvBusy = true;
  const url = await API.preview(S.photo.box, S.deco, 300).catch(() => "");
  pvBusy = false;
  if (typeof url === "string" && url) {
    $("#pvImg").src = url; $("#pvImg").hidden = false; $("#pvBox .ph0").style.display = "none";
  }
  if (pvAgain) { pvAgain = false; requestPreview(); }
}
// 확대 슬라이더 (로그 스케일): 오른쪽일수록 확대
function zoomRange() { const P = S.photo, mx = Math.min(P.w, P.h); return [Math.log(mx), Math.log(Math.max(16, mx * 0.08))]; }
function syncZoom() {
  if (!S.photo) return;
  const [a, b] = zoomRange(), v = (Math.log(S.photo.box[2]) - a) / (b - a);
  $("#zoom").value = Math.round(Math.max(0, Math.min(1, v)) * 1000);
  $("#zoomTxt").textContent = Math.round(Math.min(S.photo.w, S.photo.h) / S.photo.box[2] * 100) + "%";
}
$("#zoom").addEventListener("input", () => {
  if (!S.photo) return;
  const [a, b] = zoomRange(), v = $("#zoom").value / 1000;
  const [cx, cy] = S.photo.box;
  S.photo.box = clampBox([cx, cy, Math.exp(a + (b - a) * v)]);
  $("#zoomTxt").textContent = Math.round(Math.min(S.photo.w, S.photo.h) / S.photo.box[2] * 100) + "%";
  drawStage();
});
let drag = null;
cv.addEventListener("mousedown", (e) => { if (S.photo) { drag = { x: e.clientX, y: e.clientY, box: [...S.photo.box] }; $("#stage").focus(); } });
window.addEventListener("mousemove", (e) => {
  if (!drag) return;
  const [cx, cy, side] = drag.box;
  // 사진이 마우스를 따라 움직임 = 자르기 영역은 반대로
  S.photo.box = clampBox([cx - (e.clientX - drag.x) / view.s, cy - (e.clientY - drag.y) / view.s, side]);
  drawStage();
});
window.addEventListener("mouseup", () => drag = null);
cv.addEventListener("wheel", (e) => {
  if (!S.photo) return;
  e.preventDefault();
  const [cx, cy, side] = S.photo.box;
  S.photo.box = clampBox([cx, cy, side * (e.deltaY < 0 ? 0.93 : 1.075)]);
  syncZoom(); drawStage();
}, { passive: false });
cv.addEventListener("dblclick", () => autoFit());
$("#stage").addEventListener("keydown", (e) => {
  if (!S.photo) return;
  const step = (e.shiftKey ? 10 : 2) / view.s;
  const d = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
  if (!d) return;
  e.preventDefault();
  const [cx, cy, side] = S.photo.box;
  S.photo.box = clampBox([cx + d[0], cy + d[1], side]);
  drawStage();
});
new ResizeObserver(() => drawStage()).observe($("#stage"));
async function autoFit() {
  if (!S.photo) return;
  const r = await call("auto_box");
  if (Array.isArray(r)) { S.photo.box = clampBox(r); S.photo.auto = r; syncZoom(); drawStage(); }
}

// 사진 넣기
function readFile(file) {
  if (!file || !file.type.startsWith("image/")) { toast("이미지 파일만 넣을 수 있어요.", "err"); return; }
  const fr = new FileReader();
  fr.onload = async () => {
    busy(true, "사진 불러오는 중…");
    const r = await call("load_image", fr.result);
    busy(false);
    if (r) await setPhoto(r);
  };
  fr.readAsDataURL(file);
}
$("#drop").onclick = $("#btnOpen").onclick = () => $("#file").click();
$("#file").onchange = (e) => { readFile(e.target.files[0]); e.target.value = ""; };
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => {
  e.preventDefault();
  if ($("#pageMake").classList.contains("on")) $("#stage").classList.add("drag");
}));
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) $("#stage").classList.remove("drag"); });
document.addEventListener("drop", (e) => {
  e.preventDefault(); $("#stage").classList.remove("drag");
  if (e.dataTransfer.files.length && $("#pageMake").classList.contains("on")) readFile(e.dataTransfer.files[0]);
});
document.addEventListener("paste", (e) => {
  if (e.target.matches("input,textarea")) return;
  const it = [...(e.clipboardData?.items || [])].find((x) => x.type.startsWith("image/"));
  if (it) { e.preventDefault(); readFile(it.getAsFile()); }
});
$("#btnPaste").onclick = async () => {
  busy(true, "클립보드 읽는 중…");
  const r = await call("paste_clipboard");
  busy(false);
  if (r) setPhoto(r);
};
$("#btnAuto").onclick = autoFit;
$("#btnRevert").onclick = async () => { const r = await call("revert_original"); if (r) setPhoto(r); };
$("#btnNobg").onclick = async () => {
  if (!S.photo) return;
  const on = !S.photo.nobg;
  if (on && !S.bgReady && !await confirmBox("배경 제거 모델 받기", "배경 제거를 처음 쓰려면 AI 모델(약 170MB)을 한 번 내려받아야 해요.\n받은 뒤에는 인터넷 없이도 바로 작동해요.\n\n지금 받을까요?", "받기")) return;
  busy(true, on ? "배경 지우는 중…" : "되돌리는 중…");
  const r = await call("set_nobg", on);
  busy(false);
  if (r) { if (on) S.bgReady = true; setPhoto(r, true); }
};

/* ------------------------------------------------------------------ 꾸미기 */
function renderDeco() {
  const d = S.deco;
  $("#dCaption").checked = d.caption; $("#dRound").checked = d.rounded; $("#dBorder").checked = d.border;
  $("#dRadius").value = d.radius; $("#dRadius").disabled = !d.rounded;
  $(".deco").classList.toggle("off-cap", !d.caption);
  $("#dStyle").innerHTML = Object.entries(S.styles).map(([k, v]) => `<button class="chip ${d.style === k ? "on" : ""}" data-k="${k}">${esc(v)}</button>`).join("");
  $$("#dStyle .chip").forEach((b) => b.onclick = () => { S.deco.style = b.dataset.k; decoChanged(); });
}
function syncDecoText() {
  if (!S.decoTextDirty) { $("#dText").value = $("#fName").value.trim(); S.deco.text = $("#dText").value; requestPreview(); }
}
let decoSaveTimer;
function decoChanged() {
  renderDeco(); drawStage();
  clearTimeout(decoSaveTimer);
  decoSaveTimer = setTimeout(() => call("save_settings", { deco: S.deco }), 600);
}
$("#dCaption").onchange = () => { S.deco.caption = $("#dCaption").checked; decoChanged(); };
$("#dRound").onchange = () => { S.deco.rounded = $("#dRound").checked; decoChanged(); };
$("#dBorder").onchange = () => { S.deco.border = $("#dBorder").checked; decoChanged(); };
$("#dRadius").addEventListener("input", () => { S.deco.radius = +$("#dRadius").value; drawStage(); clearTimeout(decoSaveTimer); decoSaveTimer = setTimeout(() => call("save_settings", { deco: S.deco }), 600); });
$("#dText").addEventListener("input", () => { S.decoTextDirty = true; S.deco.text = $("#dText").value; requestPreview(); });

/* ------------------------------------------------------------------ AI */
function curAI() { return S.ai.find((a) => a.id === S.settings.ai_provider) || S.ai[0]; }
function renderAISel() {
  const sel = $("#aiSel");
  sel.innerHTML = Object.entries(GROUPS).map(([g, label]) => {
    const items = S.ai.filter((a) => a.group === g);
    return `<optgroup label="${esc(label)}">` + items.map((a) => `<option value="${a.id}">${esc(a.name)}${a.group === "free_web" ? "" : " · " + esc(a.status)}</option>`).join("") + "</optgroup>";
  }).join("");
  sel.value = curAI().id;
  updateAIButton();
}
function updateAIButton() {
  const a = curAI();
  const web = a.group === "free_web";
  $("#btnAIText").textContent = web ? "사이트 열기" : "AI 생성";
  $("#aiNote").textContent = web ? "① 사진 붙여넣기 → ② 프롬프트 붙여넣기 → 완성 사진을 복사해서 여기서 Ctrl+V"
    : (!a.ref ? "이 방식은 참고 사진을 못 보내요" : a.status === "키 없음" || a.status === "설치 안 됨" ? "설정(⚙)에서 연결해 주세요" : "");
}
$("#aiSel").onchange = () => {
  S.settings.ai_provider = $("#aiSel").value;
  call("save_settings", { ai_provider: S.settings.ai_provider });
  updateAIButton();
  if (!S.promptDirty) autoPrompt();
};
let pTimer;
function autoPromptSoon() { clearTimeout(pTimer); pTimer = setTimeout(autoPrompt, 300); }
async function autoPrompt(force = false) {
  if (S.promptDirty && !force) return;
  const t = await call("build_prompt", person(), $("#sendPhoto").checked, S.aiMode || "face", S.settings.expression || "random");
  if (typeof t === "string") { $("#prompt").value = t; if (force) S.promptDirty = false; }
}
$("#prompt").addEventListener("input", () => S.promptDirty = true);
$("#btnPrompt").onclick = () => autoPrompt(true);
$("#sendPhoto").onchange = () => {
  S.settings.send_photo = $("#sendPhoto").checked;
  call("save_settings", { send_photo: S.settings.send_photo });
  if (!S.promptDirty) autoPrompt();
};
S.aiMode = "face";
$$("#aiMode .chip").forEach((c) => c.onclick = () => {
  S.aiMode = c.dataset.m;
  $$("#aiMode .chip").forEach((x) => x.classList.toggle("on", x === c));
  $("#sendPhotoWrap").style.display = S.aiMode === "uniform" ? "none" : "";
  $("#refMode").style.display = S.aiMode === "uniform" ? "none" : "";
  $("#exprRow").hidden = S.aiMode === "uniform";
  $("#kitHint").innerHTML = S.aiMode === "uniform"
    ? "편집기 사진(선수)은 그대로 두고 옷만 바꿔요. 유니폼 사진이 없으면 <b>소속 팀의 홈 유니폼</b>으로 요청해요."
    : "유니폼 사진을 넣으면 그 유니폼을 입혀요. 없으면 <b>소속 팀의 홈 유니폼</b>으로 요청해요.";
  S.promptDirty = false; autoPrompt(true);
  if (S.aiMode === "uniform" && !S.photo) toast("유니폼을 바꿀 선수 사진을 먼저 넣어 주세요.", "info", 3500);
});
function setKitThumb(r) {
  if (!r || !r.thumb) return;
  $("#kitImg").innerHTML = `<img src="${r.thumb}">`;
  $("#btnKitX").hidden = false;
  if (!S.promptDirty) autoPrompt(true);
}
$("#btnKit").onclick = () => $("#kitFile").click();
$("#kitFile").onchange = () => {
  const f = $("#kitFile").files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = async () => setKitThumb(await call("set_kit", rd.result));
  rd.readAsDataURL(f);
  $("#kitFile").value = "";
};
$("#btnKitX").onclick = async () => {
  await call("clear_kit");
  $("#kitImg").innerHTML = "<span>유니폼<br>사진</span>";
  $("#btnKitX").hidden = true;
  if (!S.promptDirty) autoPrompt(true);
};
$("#btnStep2").onclick = async () => {
  await copyText(S.step2Prompt || $("#prompt").value);
  toast("프롬프트를 복사했어요. 사이트 입력칸에 Ctrl+V 하세요.\n완성된 사진을 복사해서 여기서 Ctrl+V 하면 편집기로 들어와요.", "ok", 6000);
  $("#step2").hidden = true;
};
$("#btnStep2X").onclick = () => $("#step2").hidden = true;
function renderExpr() {
  const cur = S.settings.expression || "random";
  $("#exprChips").innerHTML = Object.entries(S.expressions || {}).map(([k, v]) => `<button class="chip ${k === cur ? "on" : ""}" data-e="${k}">${esc(v)}</button>`).join("");
  $$("#exprChips .chip").forEach((c) => c.onclick = () => {
    S.settings.expression = c.dataset.e;
    call("save_settings", { expression: c.dataset.e });
    renderExpr();
    S.promptDirty = false; autoPrompt(true);
  });
  const rm = S.settings.ref_mode || "game";
  $$("#refMode .chip").forEach((c) => {
    c.classList.toggle("on", c.dataset.r === rm);
    c.title = c.dataset.r === "game" ? "참고 사진이 게임의 3D 얼굴일 때: 따라 그리지 말고 실제 사진으로 새로 만들어요" : "참고 사진이 실제 사람 사진일 때: 얼굴을 그대로 유지해요";
    c.onclick = () => { S.settings.ref_mode = c.dataset.r; call("save_settings", { ref_mode: c.dataset.r }); renderExpr(); S.promptDirty = false; autoPrompt(true); };
  });
  const mo = S.settings.manager_outfit || "suit";
  $$("#mgrOutfit .chip").forEach((c) => {
    c.classList.toggle("on", c.dataset.o === mo);
    c.onclick = () => { S.settings.manager_outfit = c.dataset.o; call("save_settings", { manager_outfit: c.dataset.o }); renderExpr(); S.promptDirty = false; autoPrompt(true); };
  });
}
let hintTimer;
$("#fClubHint").addEventListener("input", () => {
  clearTimeout(hintTimer);
  hintTimer = setTimeout(async () => {
    const club = $("#fClub").value.trim(), hint = $("#fClubHint").value.trim();
    if (!club) return;
    S.settings.club_hints = S.settings.club_hints || {};
    if (hint) S.settings.club_hints[club] = hint; else delete S.settings.club_hints[club];
    await call("set_club_hint", club, hint);
    if (!S.promptDirty) autoPrompt();
  }, 400);
});
$("#fClub").addEventListener("input", () => { $("#fClubHint").value = ((S.settings.club_hints || {})[$("#fClub").value.trim()]) || ""; });
$("#btnAI").onclick = async () => {
  let prompt = $("#prompt").value.trim();
  if (!prompt) { await autoPrompt(true); prompt = $("#prompt").value.trim(); }
  const a = curAI();
  const mode = S.aiMode || "face";
  if (mode === "uniform" && !S.photo) { toast("유니폼을 바꿀 선수 사진을 먼저 넣어 주세요.", "err"); return; }
  const send = $("#sendPhoto").checked && !!S.photo;
  if (a.group === "free_web") {
    const r = await call("ai_web", a.id, prompt, send, mode);
    if (!r) return;
    if (r.step2) {
      S.step2Prompt = prompt;
      $("#step2").hidden = false;
      toast(`${a.name}을 열었어요.\n① 사이트 입력칸에 Ctrl+V → 사진 ${r.files}장이 들어가요.\n② 여기서 '프롬프트 복사'를 누르고 한 번 더 Ctrl+V 하세요.`, "ok", 9000);
      return;
    }
    if (!r.clip) await copyText(prompt);
    const how = r.clip && r.files > 1 ? "선수 사진·유니폼 사진·프롬프트를 함께 복사했어요.\n사이트 입력칸을 누르고 Ctrl+V 한 번이면 같이 들어가요."
      : r.clip && r.with_photo ? "참고 사진과 프롬프트를 함께 복사했어요.\n사이트 입력칸을 누르고 Ctrl+V 한 번이면 같이 들어가요."
      : r.with_photo ? "프롬프트를 복사했어요. 참고 사진 파일이 있는 폴더도 열었으니 입력칸에 끌어다 놓아 주세요."
      : "프롬프트를 복사했어요. 사이트 입력칸에 Ctrl+V 하세요.";
    toast(`${a.name}을 열었어요.\n${how}\n완성된 사진을 복사해서 여기서 Ctrl+V 하면 편집기로 들어와요.`, "ok", 9000);
    return;
  }
  busy(true, "AI가 사진을 만드는 중…", a.name + " · 보통 10초~1분");
  $("#btnAI").disabled = true;
  const r = await call("ai_generate", a.id, prompt, send, mode);
  busy(false); $("#btnAI").disabled = false;
  if (!r) return;
  if (r.error === "need_key") { toast(`${a.name} 연결 정보가 없어요. 설정에서 넣어 주세요.`, "err"); openSettings(a.id); return; }
  await setPhoto(r);
  toast("AI 사진 완성! 위치를 맞추고 대기열에 추가하세요.", "ok");
};

/* ------------------------------------------------------------------ 3. 대기열 */
function renderQueue() {
  const el = $("#queue");
  $("#qCount").textContent = S.queue.length;
  $("#btnApply").disabled = !S.queue.length;
  if (!S.queue.length) {
    el.innerHTML = `<div class="empty"><div>${ico("layers")}<br>사진을 편집해서<br><b style="color:var(--muted)">대기열에 추가</b>해 보세요</div></div>`;
    return;
  }
  el.innerHTML = S.queue.map((q) => `
    <div class="qitem"><img src="${q.thumb}">
      <div class="tx"><div class="nm">${esc(q.name || "이름 없음")}</div>
        <div style="display:flex;gap:4px;margin-top:3px"><span class="badge uid">${esc(q.uid)}</span>${q.newgen ? '<span class="badge ng">뉴젠</span>' : ""}${q.kind === "staff" ? '<span class="badge face">스태프</span>' : q.kind === "support" ? '<span class="badge face">지원 스태프</span>' : ""}</div></div>
      <button class="x" data-id="${q.id}" title="빼기">${ico("x")}</button></div>`).join("");
  $$(".x", el).forEach((b) => b.onclick = async () => { const r = await call("queue_remove", [b.dataset.id]); if (r) { S.queue = r.queue; renderQueue(); } });
}
$("#btnAdd").onclick = async () => {
  const p = person();
  if (!/^(r-)?\d+$/.test(p.uid)) { toast("UID(숫자)를 입력하거나 검색 결과에서 인물을 골라 주세요.", "err"); $("#fUid").focus(); return; }
  if (!S.photo) { toast("먼저 사진을 넣거나 AI로 만들어 주세요.", "err"); return; }
  let r = await call("add_to_queue", p, S.photo.box, S.deco, false);
  if (r && r.confirm === "duplicate") {
    if (!await confirmBox("이미 대기열에 있어요", `UID ${p.uid}가 대기열에 있어요.\n새 사진으로 바꿀까요?`, "바꾸기")) return;
    r = await call("add_to_queue", p, S.photo.box, S.deco, true);
  }
  if (r && r.queue) { S.queue = r.queue; renderQueue(); toast(`${p.name || p.uid} 대기열에 추가`, "ok", 2000); }
};
$("#btnQClear").onclick = async () => {
  if (!S.queue.length) return;
  if (!await confirmBox("대기열 비우기", "대기열을 모두 비울까요?", "비우기", true)) return;
  const r = await call("queue_clear"); if (r) { S.queue = r.queue; renderQueue(); }
};
$("#btnApply").onclick = async () => {
  $("#btnApply").disabled = true;
  let r = await call("apply_all", false);
  if (r && r.confirm === "fm_running") {
    if (!await confirmBox("FM27이 켜져 있어요", "적용은 되지만 게임을 완전히 껐다 켜야 바뀐 사진이 보여요.\n계속할까요?", "적용")) { renderQueue(); return; }
    r = await call("apply_all", true);
  }
  if (r && r.queue) {
    S.queue = r.queue; renderQueue();
    if (r.refresh && r.refresh.ok) toast(`${r.count}명 적용 완료!\n게임에도 바로 반영했어요. 다른 화면으로 갔다 오면 바뀐 사진이 보여요.`, "ok", 7000);
    else if (r.refresh) toast(`${r.count}명 적용 완료!\n게임 실시간 반영은 실패했어요: ${r.refresh.message}\nFM27을 껐다 켜면 반영돼요.`, "err", 7000);
    else toast(`${r.count}명 적용 완료!\nFM27을 완전히 종료한 뒤 다시 켜면 반영돼요.`, "ok", 6000);
    pollStatus();
    if (r.conflicts && r.conflicts.length) {
      await confirmBox("다른 페이스팩과 겹쳐요", "아래 인물은 다른 페이스팩도 사진을 지정하고 있어서 얼굴이 안 바뀔 수 있어요.\n\n" +
        r.conflicts.slice(0, 12).map((c) => `• ${c.name} (${c.uid}) — ${c.packs.join(", ")}`).join("\n"), "확인");
    }
    refreshAppliedCount();
    doSearch();
  } else renderQueue();
};

/* ------------------------------------------------------------------ 적용된 얼굴 */
async function refreshAppliedCount() {
  const r = await call("applied_list");
  if (Array.isArray(r)) { S.applied = r; $("#appliedCnt").textContent = r.length; }
}
async function loadApplied() { await refreshAppliedCount(); S.aSel.clear(); renderApplied(); }
function renderApplied() {
  const q = $("#aq").value.trim().toLowerCase();
  const list = S.applied.filter((a) => !q || `${a.name} ${a.club} ${a.uid}`.toLowerCase().includes(q));
  $("#aStat").textContent = `총 ${S.applied.length}명` + (q ? ` · 표시 ${list.length}` : "") + (S.aSel.size ? ` · 선택 ${S.aSel.size}` : "");
  if (!S.applied.length) {
    $("#agrid").innerHTML = `<div class="empty" style="grid-column:1/-1;padding:80px">${ico("layers")}<br>아직 적용한 얼굴이 없어요</div>`;
    return;
  }
  $("#agrid").innerHTML = list.map((a) => `
    <div class="fcard ${S.aSel.has(a.uid) ? "sel" : ""}" data-uid="${a.uid}">
      <img src="${a.thumb}">
      <span class="chk"><svg viewBox="0 0 24 24"><path d="m5 12 5 5L20 7"/></svg></span>
      <div class="tags">${a.newgen ? '<span class="badge ng">뉴젠</span>' : ""}</div>
      <div class="foot"><div class="tx"><div class="nm">${esc(a.name || "이름 없음")}</div>
        <div class="sub">${esc(a.club || "")}${a.club ? " · " : ""}${esc(a.uid)}</div></div>
        <button class="btn icon sm" data-edit="${a.uid}" title="다시 편집">${ico("edit")}</button></div>
    </div>`).join("");
  $$(".fcard").forEach((c) => c.onclick = (e) => {
    const ed = e.target.closest("[data-edit]");
    if (ed) return editApplied(ed.dataset.edit);
    const u = c.dataset.uid;
    S.aSel.has(u) ? S.aSel.delete(u) : S.aSel.add(u);
    renderApplied();
  });
}
$("#aq").addEventListener("input", renderApplied);
$("#btnSelAll").onclick = () => {
  const vis = $$(".fcard").map((c) => c.dataset.uid);
  const all = vis.every((u) => S.aSel.has(u));
  vis.forEach((u) => all ? S.aSel.delete(u) : S.aSel.add(u));
  renderApplied();
};
$("#btnADel").onclick = async () => {
  if (!S.aSel.size) { toast("삭제할 얼굴을 골라 주세요."); return; }
  if (!await confirmBox("얼굴 삭제", `${S.aSel.size}명의 사진을 게임에서 빼고 파일을 지울까요?\n(config.xml 백업은 남아요)`, "삭제", true)) return;
  const r = await call("applied_remove", [...S.aSel]);
  if (Array.isArray(r)) { S.applied = r; S.aSel.clear(); $("#appliedCnt").textContent = r.length; renderApplied(); toast("삭제했어요.", "ok"); }
};
async function editApplied(uid) {
  const r = await call("applied_edit", uid);
  if (!r) return;
  $$(".tab")[0].click();
  S.selUid = null;
  fillPerson(r.person);
  showView("edit");
  showCurrent(await call("current_face", r.person.uid));
  if (r.photo) await setPhoto(r.photo);
  S.promptDirty = false; autoPrompt();
}
$("#btnConflict").onclick = async () => {
  toast("다른 페이스팩과 겹치는지 검사 중…");
  const r = await call("check_conflicts");
  if (!Array.isArray(r)) return;
  if (!r.length) toast("겹치는 인물이 없어요.", "ok");
  else confirmBox("겹치는 인물 " + r.length + "명", "다른 config.xml이 같은 인물을 지정하고 있어요. 얼굴이 안 바뀌면 그쪽 줄을 지워야 해요.\n\n" +
    r.slice(0, 15).map((c) => `• ${c.name} (${c.uid})\n   ${c.packs.join("\n   ")}`).join("\n"), "확인");
};

/* ------------------------------------------------------------------ 설정 */
let setAI = {}, setSel = null, setUse = null;
function openSettings(focusId) {
  const s = S.settings;
  $("#sG").value = s.graphics_dir || ""; $("#sSize").value = s.output_size || 512; $("#sTpl").value = s.prompt_template || ""; $("#sLang").value = s.prompt_lang || "ko";
  setAI = {};
  S.ai.forEach((a) => setAI[a.id] = { key: a.key, account: a.account, model: a.model });
  setUse = s.ai_provider;
  setSel = focusId || s.ai_provider;
  renderAIList();
  $("#mSettings").classList.add("on");
}
function renderAIList() {
  $("#aiList").innerHTML = Object.entries(GROUPS).map(([g, label]) =>
    `<div class="aigrp">${esc(label)}</div>` + S.ai.filter((a) => a.group === g).map((a) => {
      const ok = ["바로 사용", "키 있음", "설치됨"].includes(a.status);
      return `<div class="airow ${a.id === setSel ? "on" : ""} ${a.id === setUse ? "use" : ""}" data-id="${a.id}"><span class="rd"></span>
        <span class="nm">${esc(a.name)}</span><span class="st ${ok ? "ok" : ""}">${esc(a.status)}</span></div>`;
    }).join("")).join("");
  $$("#aiList .airow").forEach((r) => r.onclick = () => { setSel = r.dataset.id; setUse = r.dataset.id; renderAIList(); });
  renderAIDetail();
}
function renderAIDetail() {
  const a = S.ai.find((x) => x.id === setSel);
  if (!a) return;
  const c = setAI[a.id] || {};
  const [tc, tl] = TAG[a.group];
  let fields = "";
  if (a.group === "api" || a.id === "cloudflare") {
    if (a.id === "cloudflare") fields += `<div><span class="lbl">계정 ID (Account ID)</span><label class="field"><input data-f="account" value="${esc(c.account || "")}"></label></div>`;
    fields += `<div><span class="lbl">${a.id === "cloudflare" ? "토큰 (API Token)" : "API 키"}</span><div class="rowf"><label class="field"><input data-f="key" type="password" value="${esc(c.key || "")}"></label><button class="btn" id="btnShowKey">보기</button></div></div>`;
    fields += `<div><span class="lbl">모델 <span class="hint">· 비우면 기본값 ${esc(a.default_model)}</span></span><label class="field"><input data-f="model" value="${esc(c.model || "")}" placeholder="${esc(a.default_model)}"></label></div>`;
    if (KEY_URL[a.id]) fields += `<div class="hint"><a data-url="${KEY_URL[a.id]}">발급 페이지 열기</a></div>`;
  }
  $("#aiDetail").innerHTML = `<h4>${esc(a.name)}<span class="tag ${tc}">${tl}</span></h4>
    <div class="muted" style="font-size:12px">${esc(a.desc)}</div>
    <ol>${(HOWTO[a.id] || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ol>${fields}`;
  $$("#aiDetail [data-f]").forEach((inp) => inp.addEventListener("input", () => {
    setAI[a.id] = setAI[a.id] || {}; setAI[a.id][inp.dataset.f] = inp.value;
  }));
  const sk = $("#btnShowKey");
  if (sk) sk.onclick = () => { const k = $('#aiDetail [data-f="key"]'); k.type = k.type === "password" ? "text" : "password"; };
  $$("#aiDetail [data-url]").forEach((l) => l.onclick = () => call("open_url", l.dataset.url));
}
$("#btnSettings").onclick = () => openSettings();
$$("[data-close]").forEach((b) => b.onclick = () => b.closest(".modal").classList.remove("on"));
$("#lnkDefault").onclick = () => $("#sTpl").value = "";
$("#btnPickG").onclick = async () => { const r = await call("pick_folder", $("#sG").value); if (r) $("#sG").value = r; };
$("#btnSaveSettings").onclick = async () => {
  const r = await call("save_settings", {
    graphics_dir: $("#sG").value, output_size: +$("#sSize").value || 512, prompt_template: $("#sTpl").value, prompt_lang: $("#sLang").value,
    ai_provider: setUse, ai_cfg: setAI,
  });
  if (!r) return;
  applyState(r);
  $("#mSettings").classList.remove("on");
  toast("설정을 저장했어요.", "ok", 2000);
  if (!S.promptDirty) autoPrompt();
};
$("#btnFolder").onclick = () => call("open_pack_dir");
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $$(".modal.on").forEach((m) => m.classList.remove("on")); });

/* ------------------------------------------------------------------ 상단 상태 배지 */
let ST = null, popKind = null;
const fmtTime = (t) => t ? new Date(t * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
function setPill(id, cls, text) { const b = $(id); b.className = "pill " + cls + (popKind && b.dataset.pop === popKind ? " on" : ""); $("span", b).textContent = text; }
async function pollStatus() {
  const r = await API.status_all().catch(() => null);
  if (!r || r.error) return;
  ST = r;
  const sv = r.save, g = r.game;
  setPill("#bSave", sv.loaded ? (sv.changed || !sv.exists ? "warn" : "ok") : "", sv.loaded ? (sv.changed ? "세이브 바뀜 · 다시 읽기" : sv.name) : "세이브 없음");
  setPill("#bGame", g.running ? (g.connected ? "ok" : "warn") : "", g.running ? (g.connected ? "FM27 실행 중 · 연결됨" : "FM27 실행 중") : (g.game_found ? "FM27 꺼짐" : "FM27 못 찾음"));
  const pOk = g.plugin_installed && g.plugin_up_to_date && g.bepinex;
  setPill("#bPlugin", pOk ? "ok" : (g.game_found ? "warn" : ""), pOk ? "플러그인" : g.plugin_installed ? "플러그인 업데이트" : "플러그인 설치 필요");
  $("#applyHint").textContent = g.connected && ST.auto_refresh
    ? "게임과 연결돼 있어요. 적용하면 게임에 바로 반영돼요."
    : "적용 후 FM27을 완전히 껐다 켜야 바뀐 사진이 보여요. (플러그인이 있으면 바로 반영)";
  const ver = sv.version || 0, ic = (sv.index && sv.index.count) || 0;
  const readingNow = !!(sv.reading && sv.reading.active);
  if (ver !== S.peopleVer || ic !== S.indexCount || readingNow !== S.wasReading) {
    const first = S.peopleVer === -1;
    S.peopleVer = ver; S.indexCount = ic; S.wasReading = readingNow;
    if (sv.loaded && (!S.people.loaded || !first)) { const st = await call("get_state"); if (st) S.people = st.people; }
    if (!first || sv.loaded) { if ($("#viewBrowse").classList.contains("on")) doSearch(true); }
  }
  if (popKind) renderPop();
}
function row(k, v, cls = "") { return `<div class="k">${esc(k)}</div><div class="v ${cls}">${esc(v)}</div>`; }
function renderPop() {
  if (!ST || !popKind) return;
  const sv = ST.save, g = ST.game, el = $("#pop");
  let html = "";
  if (popKind === "save") {
    const c = sv.counts || {};
    html = `<h4><i class="${sv.loaded ? (sv.changed ? "warn" : "ok") : ""}"></i>${sv.loaded ? "세이브가 연결되어 있어요" : "연결된 세이브가 없어요"}</h4>
      <div class="kv">${sv.loaded ? row("이 세이브", sv.name) + row("위치", sv.path, "dim") + row("선수", (c.player || 0).toLocaleString() + "명")
        + row("스태프", (c.staff || 0).toLocaleString() + "명") + row("읽은 시각", fmtTime(sv.read_at))
        + row("상태", !sv.exists ? "세이브 파일이 없어졌어요" : sv.changed ? "게임에서 새로 저장됐어요 — 다시 읽어 주세요" : "최신", !sv.exists || sv.changed ? "warn" : "ok")
        : row("안내", sv.reading && sv.reading.active ? "세이브를 읽는 중이에요…" : "FM27에서 세이브를 불러오거나 저장하면 자동으로 연결돼요.")}
        ${sv.reading && sv.reading.active ? row("읽는 중", (sv.reading.path || "").split(/[\\/]/).pop(), "warn") : ""}</div>
      <div style="margin-top:10px"><label class="switch"><input type="checkbox" id="optFollow" ${sv.follow ? "checked" : ""}><i></i>게임에서 새로 저장하면 자동으로 다시 읽기</label></div>
      <div class="acts">${sv.loaded ? `<button class="btn" data-act="reload">${ico("refresh")}다시 읽기</button>` : ""}<button class="btn ${sv.loaded ? "" : "primary"}" data-act="readcur">게임의 최근 세이브</button><button class="btn" data-act="pick">${ico("folder")}직접 고르기</button></div>`;
  } else if (popKind === "game") {
    html = `<h4><i class="${g.running ? (g.connected ? "ok" : "warn") : ""}"></i>${g.running ? "FM27이 켜져 있어요" : g.game_found ? "FM27이 꺼져 있어요" : "FM27을 찾지 못했어요"}</h4>
      <div class="kv">${row("상태", g.running ? "실행 중" : "꺼짐", g.running ? "ok" : "")}
        ${row("게임 연결", g.connected ? `연결됨 (플러그인 ${g.heartbeat.plugin || ""})` : g.running ? "플러그인 응답 없음" : "-", g.connected ? "ok" : g.running ? "warn" : "")}
        ${row("설치 폴더", g.game_dir || "찾지 못함", "dim")}${row("graphics", ST.graphics_dir, "dim")}</div>
      <div class="acts">${!g.running && g.game_found ? `<button class="btn primary" data-act="launch">FM27 켜기</button>` : ""}${g.game_found ? `<button class="btn" data-act="gamefolder">${ico("folder")}설치 폴더</button>` : ""}</div>
      ${g.running && !g.connected ? `<div class="note">게임은 켜져 있는데 플러그인이 답하지 않아요. 플러그인이 설치돼 있는지, 세이브를 불러왔는지 확인해 주세요.</div>` : ""}`;
  } else if (popKind === "plugin") {
    const pOk = g.plugin_installed && g.plugin_up_to_date && g.bepinex;
    const diagOn = g.connected && g.heartbeat && g.heartbeat.diagnosing;
    html = `<h4><i class="${pOk ? "ok" : "warn"}"></i>${pOk ? "플러그인이 설치되어 있어요" : g.plugin_installed ? "플러그인을 업데이트해야 해요" : "플러그인이 설치되어 있지 않아요"}</h4>
      <div class="kv">${row("BepInEx", g.bepinex ? (g.bepinex_ready ? "설치됨" : "설치됨 · 게임을 한 번 켜야 준비돼요") : "없음 — 먼저 설치해 주세요", g.bepinex ? "ok" : "warn")}
        ${row("플러그인", g.plugin_installed ? (g.plugin_up_to_date ? "설치됨 (최신)" : "예전 버전") : "없음", g.plugin_installed && g.plugin_up_to_date ? "ok" : "warn")}
        ${row("게임 연결", g.connected ? "연결됨" : g.running ? "응답 없음" : "게임 꺼짐", g.connected ? "ok" : "")}
        ${g.heartbeat && g.heartbeat.last ? row("최근 결과", g.heartbeat.last, "dim") : ""}</div>
      <div class="note">플러그인이 있으면 '한 번에 적용' 후 게임을 끄지 않아도 사진이 바로 바뀌어요.${g.bepinex ? "" : `<br><b style="color:var(--warn)">BepInEx 6 (Unity IL2CPP, win-x64, be.793 이상)</b>를 먼저 FM27 설치 폴더에 설치하고 게임을 한 번 켰다 꺼 주세요. <a data-act="bepinex">BepInEx 받는 곳</a>`}</div>
      <div style="margin-top:10px"><label class="switch"><input type="checkbox" id="optAuto" ${ST.auto_refresh ? "checked" : ""}><i></i>적용 후 게임에 자동 반영</label></div>
      <div class="acts">${!pOk && g.bepinex ? `<button class="btn primary" data-act="install">${ico("upload")}${g.plugin_installed ? "플러그인 업데이트" : "플러그인 설치"}</button>` : ""}
        ${g.connected ? `<button class="btn" data-act="refresh">${ico("refresh")}지금 반영</button>` : ""}</div>
      <hr><div class="k" style="font-size:12px;color:var(--muted);font-weight:700">진단 (감독 사진·지원 스태프 작업용)</div>
      <div class="note" style="margin-top:6px">진단을 켜고 2분 동안 게임에서 내 감독 프로필, 그리고 언론 담당자·개인 비서처럼 얼굴이 뜨는 화면(받은 메시지 등)을 차례로 열어 주세요. 끝나면 진단 파일을 보내 주시면 돼요.</div>
      <div class="acts">${g.connected ? (diagOn ? `<button class="btn" data-act="diagstop">진단 끝내기</button>` : `<button class="btn" data-act="diag">진단 시작 (2분)</button>`) : ""}<button class="btn" data-act="diagfolder">${ico("folder")}진단 파일</button></div>`;
  }
  el.innerHTML = html;
  const b = $(`.pill[data-pop="${popKind}"]`).getBoundingClientRect();
  el.style.left = Math.max(12, Math.min(window.innerWidth - 372, b.right - 360)) + "px";
  $$("[data-act]", el).forEach((x) => x.onclick = () => popAction(x.dataset.act, x));
  const of = $("#optFollow", el);
  if (of) of.onchange = async () => { await call("set_option", "follow_save", of.checked); pollStatus(); };
  const oa = $("#optAuto", el);
  if (oa) oa.onchange = async () => { await call("set_option", "auto_refresh", oa.checked); pollStatus(); };
}
async function popAction(act, btn) {
  if (act === "reload") { closePop(); await reloadSave(); }
  else if (act === "pick") { closePop(); await pickSave(); }
  else if (act === "readcur") { closePop(); await readSaveNow("current"); }
  else if (act === "launch") { await call("launch_game"); toast("Steam으로 FM27을 켰어요.", "ok", 2500); }
  else if (act === "gamefolder") call("open_game_folder");
  else if (act === "diagfolder") call("open_diag_folder");
  else if (act === "bepinex") call("open_url", ST.bepinex_url);
  else if (act === "install") {
    const g = ST.game;
    if (g.running) { toast("FM27이 켜져 있어요. 게임을 완전히 끈 다음 설치해 주세요.", "err"); return; }
    if (!await confirmBox("플러그인 설치", "FM27 Face Studio 플러그인을 BepInEx\\plugins 폴더에 넣어요. BepInEx와 다른 플러그인은 건드리지 않아요.\n\n게임 폴더(Program Files)에 쓰려면 관리자 권한이 필요해요. 권한 창이 뜨면 '예'를 눌러 주세요.\n\n설치할까요?", "설치")) return;
    btn.disabled = true; btn.textContent = "설치 중…";
    const r = await call("install_plugin");
    if (r && r.done) toast("설치 완료: " + r.done.join(", ") + "\n게임을 켜면 플러그인이 적용돼요.", "ok", 7000);
    pollStatus();
  } else if (act === "refresh") {
    btn.disabled = true;
    const r = await call("plugin_refresh");
    if (r) toast(r.message, r.ok ? "ok" : "err", 6000);
    pollStatus();
  } else if (act === "diag" || act === "diagstop") {
    const r = await call(act === "diag" ? "plugin_diag" : "plugin_diag_stop", 120);
    if (r) toast(r.message, r.ok ? "ok" : "err", 9000);
    pollStatus();
  }
}
function closePop() { popKind = null; $("#pop").classList.remove("on"); $$(".pill").forEach((p) => p.classList.remove("on")); }
$$(".pill").forEach((p) => p.onclick = (e) => {
  e.stopPropagation();
  if (popKind === p.dataset.pop) { closePop(); return; }
  popKind = p.dataset.pop;
  $$(".pill").forEach((x) => x.classList.toggle("on", x === p));
  $("#pop").classList.add("on");
  renderPop(); pollStatus();
});
document.addEventListener("click", (e) => { if (popKind && !e.target.closest("#pop") && !e.target.closest(".pill") && !e.target.closest(".modal")) closePop(); });

/* ------------------------------------------------------------------ 시작 */
function applyState(st) {
  S.settings = st.settings; S.ai = st.ai; S.styles = st.styles; S.defaultPrompt = st.default_prompt;
  S.people = st.people; S.queue = st.queue; S.bgReady = st.bg_ready; S.expressions = st.expressions;
  S.deco = { ...S.deco, ...(st.settings.deco || {}), text: S.deco.text };
  $("#ver").textContent = "v" + st.version;
  $("#sendPhoto").checked = !!st.settings.send_photo;
  if (!st.face_ai) $("#btnAuto").title = "얼굴 인식 모델이 없어 기본 위치로 맞춰요";
  renderQueue(); renderDeco(); renderAISel(); renderExpr();
}
(async () => {
  API = await ready();
  const st = await call("get_state");
  const boot = $("#boot");
  if (boot) { boot.classList.add("done"); setTimeout(() => boot.remove(), 400); }
  if (!st) return;
  applyState(st);
  updateCard();
  autoPrompt();
  refreshAppliedCount();
  doSearch(true);
  pollStatus();
  refreshMax();
  setInterval(pollStatus, 3000);
})();


/* ------------------------------------------------------------------ 단축키 */
function openKeys() { $("#keysModal").classList.add("on"); }
$("#keysX").onclick = () => $("#keysModal").classList.remove("on");
$("#btnKeys").onclick = openKeys;
function typing(e) {
  const t = e.target;
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}
document.addEventListener("keydown", (e) => {
  const anyModal = $(".modal.on");
  if (e.key === "Escape") {
    if (anyModal) { anyModal.classList.remove("on"); e.preventDefault(); return; }
    if ($("#pop").classList.contains("on")) { closePop(); return; }
    if (inEdit() && !typing(e)) { e.preventDefault(); goBack(); }
    else if (inEdit() && typing(e)) e.target.blur();
    return;
  }
  if (anyModal) return;
  const ctrl = e.ctrlKey || e.metaKey;
  if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
    e.preventDefault();
    if (!inEdit()) return;
    if (e.key === "ArrowRight") stepPerson(1);
    else if ((S.curIdx ?? -1) > 0) stepPerson(-1); else goBack();
    return;
  }
  if (ctrl && e.shiftKey && (e.key === "C" || e.key === "c")) {
    if (!inEdit()) return;
    e.preventDefault();
    copyText($("#prompt").value).then(() => toast("프롬프트를 복사했어요.", "ok", 1800));
    return;
  }
  if (ctrl && (e.key === "g" || e.key === "G")) { if (inEdit()) { e.preventDefault(); $("#btnAI").click(); } return; }
  if (ctrl && e.key === "Enter") { if (inEdit() && !$("#btnAdd").disabled) { e.preventDefault(); $("#btnAdd").click(); } return; }
  if (ctrl && (e.key === "f" || e.key === "F")) {
    e.preventDefault();
    if (!$("#pageMake").classList.contains("on")) $$(".tab")[0].click();
    if (inEdit()) goBack();
    setTimeout(() => { $("#qName").focus(); $("#qName").select(); }, 60);
    return;
  }
  if (e.key === "?" && !typing(e)) { e.preventDefault(); openKeys(); }
});
// 마우스 뒤로가기 버튼(엄지 버튼)
window.addEventListener("mousedown", (e) => { if (e.button === 3 || e.button === 4) e.preventDefault(); });
window.addEventListener("mouseup", (e) => {
  if (e.button === 3) { e.preventDefault(); goBack(); }
  else if (e.button === 4) { e.preventDefault(); if (inEdit()) stepPerson(1); }
});

/* ------------------------------------------------------------------ 제목줄 (창 버튼·크기 조절) */
async function refreshMax() {
  const r = await call("win_state");
  const m = !!(r && r.maximized);
  document.body.classList.toggle("maxed", m);
  $("#wMax").title = m ? "이전 크기로" : "최대화";
  $("#wMax").innerHTML = m
    ? '<svg viewBox="0 0 12 12"><rect x="2" y="3.6" width="6.4" height="6.4" rx="1"/><path d="M4 3.6V2.6a.6.6 0 0 1 .6-.6h4.8a.6.6 0 0 1 .6.6v4.8a.6.6 0 0 1-.6.6H8.4"/></svg>'
    : '<svg viewBox="0 0 12 12"><rect x="2.2" y="2.2" width="7.6" height="7.6" rx="1"/></svg>';
}
$("#wMin").onclick = () => call("win_min");
$("#wMax").onclick = async () => { await call("win_toggle_max"); refreshMax(); };
$("#wClose").onclick = () => call("win_close");
["#dragFill", ".brand"].forEach((sel) => $(sel).addEventListener("dblclick", async () => { await call("win_toggle_max"); refreshMax(); }));
(function grips() {
  let drag = null, pending = null, busyR = false;
  async function flush() {
    if (busyR || !pending) return;
    busyR = true;
    const p = pending; pending = null;
    await call("win_resize", p.w, p.h, p.k);
    busyR = false;
    if (pending) flush();
  }
  $$(".grip").forEach((g) => g.addEventListener("mousedown", async (e) => {
    e.preventDefault();
    const st = await call("win_state");
    if (!st || st.maximized) return;
    drag = { kind: g.dataset.g, x: e.screenX, y: e.screenY, w: st.width, h: st.height };
  }));
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const dx = e.screenX - drag.x, dy = e.screenY - drag.y, k = drag.kind;
    const dw = k.includes("r") ? dx : k.includes("l") ? -dx : 0;
    const dh = k.includes("b") ? dy : k.includes("t") ? -dy : 0;
    pending = { w: Math.max(1240, drag.w + dw), h: Math.max(760, drag.h + dh), k };
    flush();
  });
  window.addEventListener("mouseup", () => { drag = null; });
})();
