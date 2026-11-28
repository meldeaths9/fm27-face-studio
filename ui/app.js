"use strict";
/* FM Face Studio — 화면 로직 */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ico = (n, cls = "i") => `<svg class="${cls}"><use href="#i-${n}"/></svg>`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const GROUPS = { local: "내 PC · 무료", free_web: "무료 · 웹에서 직접", free_auto: "무료 · 자동", sub: "구독", api: "API 키 · 쓴 만큼 요금" };
const TAG = { local: ["free", "내 PC"], free_web: ["free", "무료"], free_auto: ["free", "무료"], sub: ["sub", "구독"], api: ["paid", "유료"] };
const HOWTO = {
  web_gemini: ["'사이트 열기'를 누르면 프롬프트가 복사되고 제미나이가 열려요.", "참고 사진을 켰으면 사진 파일이 있는 폴더가 같이 열려요. 사진을 제미나이 입력창에 끌어다 놓아요.", "입력창에 Ctrl+V로 프롬프트를 붙여넣고 보내요.", "완성된 사진을 우클릭 → 이미지 복사 후, 이 프로그램에서 Ctrl+V."],
  web_chatgpt: ["'사이트 열기'를 누르면 프롬프트가 복사되고 챗GPT가 열려요.", "참고 사진을 켰으면 사진 파일을 입력창에 끌어다 놓아요.", "Ctrl+V로 프롬프트를 붙여넣고 보내요.", "완성된 사진을 복사해서 이 프로그램에서 Ctrl+V."],
  web_grok: ["'사이트 열기'를 누르면 프롬프트가 복사되고 그록 Imagine이 열려요.", "참고 사진을 켰으면 사진 파일을 끌어다 놓아요.", "Ctrl+V로 프롬프트를 붙여넣고 만들어요.", "완성된 사진을 복사해서 이 프로그램에서 Ctrl+V."],
  cloudflare: ["dash.cloudflare.com 에서 무료 계정을 만들어요.", "오른쪽 위 계정 메뉴의 Account ID를 복사해 아래 '계정 ID'에 넣어요.", "내 프로필 → API 토큰 → 토큰 만들기 → 'Workers AI' 템플릿으로 만든 토큰을 '토큰'에 넣어요.", "하루 무료 사용량 안에서 버튼 하나로 생성돼요. 참고 사진은 못 보내요."],
  local: ["엔비디아(RTX) 그래픽카드가 필요해요. 그래픽카드 메모리 8GB 이상.", "첫 화면의 'AI로 한꺼번에 그리기' → 그리는 곳에서 '내 PC 그림도구'를 고르면 설치·지우기 칸이 나와요.", "처음 설치할 때 20GB 안팎을 받아요."],
  codex: ["ChatGPT 유료 구독(Plus 이상)이 필요해요.", "Node.js 설치 후 명령 프롬프트에서: npm i -g @openai/codex", "codex login 으로 ChatGPT 계정 로그인.", "프로그램을 다시 켜면 '설치됨'으로 바뀌어요. 한 장에 30초~1분 걸려요."],
  gemini: ["aistudio.google.com/apikey 에서 키를 만들어요.", "이미지 생성은 결제를 등록한 계정에서만 돼요 (무료 키는 오류).", "키를 아래에 넣어요."],
  openai: ["platform.openai.com/api-keys 에서 키를 만들어요.", "크레딧 충전이 필요해요.", "키를 아래에 넣어요."],
  xai: ["console.x.ai 에서 키를 만들어요.", "크레딧 충전이 필요해요.", "키를 아래에 넣어요. 참고 사진은 못 보내요."],
};
const BILLING_URL = { gemini: "https://aistudio.google.com/billing", openai: "https://platform.openai.com/settings/organization/billing/overview", xai: "https://console.x.ai/" };
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
  deco: { caption: false, text: "", style: "gold", rounded: false, radius: 14, border: false, text_color: "", border_color: "" },
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
function confirmBox(title, body, yes = "확인", danger = false, no = "취소") {
  return new Promise((res) => {
    $("#cTitle").textContent = title;
    $("#cBody").textContent = body;
    const y = $("#cYes"), n = $("#cNo");
    y.textContent = yes; n.textContent = no;
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
  const club = S.teamClub && S.teamClub.name === t ? S.teamClub.cuid : "";
  const r = await call("browse", n, t, S.kind, S.filter, 0, 50, S.kind === "player" ? S.squad : "", club);
  bLoading = false;
  if (!r) return;
  S.bTotal = r.total; S.bEmpty = r.empty_query; S.bIndex = r.index;
  S.bItems = r.items; S.bMax = r.max || 50;
  $("#abCnt").textContent = r.total ? `지금 목록 ${r.total.toLocaleString()}명 중에서 골라 AI로 그려요` : "지금 목록의 사람들을 AI로 그려요";
  renderBrowse(reset);
}
function cardHtml(p, i) {
  const tag = p.queued ? '<span class="tag queued">대기 중</span>' : p.face_state === "game" ? '<span class="tag game" title="사진이 없어서 게임 얼굴을 보여 줘요">게임 얼굴</span>' : p.face_state === "ours" ? '<span class="tag ours">내가 넣은 사진</span>' : p.face_state === "none" ? '<span class="tag none">사진 없음</span>' : `<span class="tag">${esc(p.pack)}</span>`;
  const tag2 = p.me ? '<span class="tag2">내 감독</span>' : p.newgen ? '<span class="tag2" style="background:rgba(31,209,165,.85);color:#03261c">뉴젠</span>' : "";
  const sq = p.squad && p.squad !== "1군" ? ` · ${esc(p.squad)}` : "";
  return `<div class="pcard2" data-i="${i}">${tag}${tag2}
    <div class="ph2${p.face_state === "game" ? " gameface" : ""}">${p.face ? `<img src="${p.face}" loading="lazy">` : "사진 없음"}<div class="dropcue">사진을 놓으면<br>바로 대기열에</div></div>
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
  $$(".pcard2", g).forEach((c) => bindCardDrop(c));
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
/* 팀 고르기: 이름이 같은 다른 클럽(예: 우루과이 리버풀)과 섞이지 않게 목록에서 정확히 고른다 */
S.teamClub = null;
let ddTimer;
function setTeamClub(c) {
  S.teamClub = c; $("#qTeamOk").hidden = !c; $("#qTeamF").classList.toggle("picked", !!c);
}
$("#qTeam").addEventListener("input", () => {
  if (S.teamClub && $("#qTeam").value.trim() !== S.teamClub.name) setTeamClub(null);
  clearTimeout(ddTimer);
  ddTimer = setTimeout(async () => {
    const q = $("#qTeam").value.trim(), dd = $("#teamDD");
    if (!q || S.teamClub) { dd.hidden = true; return; }
    const list = await call("clubs", q) || [];
    if (!list.length) { dd.hidden = true; return; }
    dd.innerHTML = list.map((c, i) => `<div class="tdi" data-i="${i}"><b>${esc(c.name)}</b>${c.mine ? ' <span class="tg">내 팀</span>' : ""}${c.alt ? ` <span class="tg2">${esc(c.alt)}</span>` : ""}<small>선수 ${c.players}명${c.example ? " · 예: " + esc(c.example) : ""}</small></div>`).join("");
    $$(".tdi", dd).forEach((el) => el.onmousedown = (e) => {
      e.preventDefault();
      const c = list[+el.dataset.i];
      $("#qTeam").value = c.name; setTeamClub(c); dd.hidden = true; doSearch(true);
    });
    dd.hidden = false;
  }, 180);
});
$("#qTeam").addEventListener("blur", () => setTimeout(() => { $("#teamDD").hidden = true; }, 120));
$("#qTeam").addEventListener("keydown", (e) => { if (e.key === "Escape") $("#teamDD").hidden = true; });
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
  setTeamClub(null);
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
let pvGen = 0;
function resetEditor() {
  pvGen++;
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
  if (r && r.look) lk.textContent = "게임 외모 · " + r.look;
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
  resetEditor();          // 앞 사람 사진이 오른쪽 미리보기에 남지 않게 먼저 비운다
  S.cur = p;
  loadGameKits(p);
  S.selUid = p.uid;
  S.curIdx = typeof idx === "number" ? idx : -1;
  fillPerson(p);
  showView("edit");
  updatePN();
  S.promptDirty = false;
  const cur = await call("current_face", p.uid);
  showCurrent(cur || { face: "" });
  if (p.queued) {
    busy(true, "대기열 사진 불러오는 중…");
    const r = await call("load_queued", p.uid);
    busy(false);
    if (r && !r.error) { await setPhoto(r); toast("대기열에 넣었던 사진이에요. 고친 뒤 다시 대기열에 넣으면 바뀌어요.", "ok", 2500); autoPrompt(); return; }
  }
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
  const gen = pvGen;
  const url = await API.preview(S.photo.box, S.deco, 300).catch(() => "");
  pvBusy = false;
  if (gen !== pvGen || !S.photo) { pvAgain = false; return; }     // 그 사이 다른 사람으로 넘어감
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
  if (inEdit()) $("#stage").classList.add("drag");
}));
document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) $("#stage").classList.remove("drag"); });
document.addEventListener("drop", (e) => {
  e.preventDefault(); $("#stage").classList.remove("drag");
  if (e.dataTransfer.files.length && inEdit()) readFile(e.dataTransfer.files[0]);
  else if (e.dataTransfer.files.length && $("#viewBrowse").classList.contains("on") && !$("#bulkModal").classList.contains("on")) openBulk(Array.from(e.dataTransfer.files));
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
  $(".deco").classList.toggle("on-round", !!d.rounded);
  $("#dStyle").innerHTML = Object.entries(S.styles).map(([k, v]) => `<button class="chip ${d.style === k ? "on" : ""}" data-k="${k}">${esc(v)}</button>`).join("");
  $$("#dStyle .chip").forEach((b) => b.onclick = () => { S.deco.style = b.dataset.k; decoChanged(); });
  const def = STYLE_COL[d.style] || STYLE_COL.gold;
  $("#dTextCol").value = d.text_color || def[0]; $("#dBorderCol").value = d.border_color || def[1];
  $("#dTextColW").hidden = !d.caption; $("#dBorderColW").hidden = !d.border;
  $("#dTextColW").classList.toggle("custom", !!d.text_color); $("#dBorderColW").classList.toggle("custom", !!d.border_color);
}
const STYLE_COL = { gold: ["#dec38b", "#e0d1af"], white: ["#ffffff", "#ffffff"], navy: ["#ecf0fa", "#7b8cff"] };
$("#dTextCol").oninput = (e) => { S.deco.text_color = e.target.value; decoChanged(); };
$("#dBorderCol").oninput = (e) => { S.deco.border_color = e.target.value; decoChanged(); };
$$(".dcol [data-reset]").forEach((b) => b.onclick = (e) => { e.preventDefault(); S.deco[b.dataset.reset] = ""; decoChanged(); });
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
/* 게임 유니폼 (플러그인이 클럽 화면에서 모아 둔 실제 유니폼 그림) */
S.kitSrc = ""; S.gkits = {}; S.gkitKind = "";
async function loadGameKits(p) {
  S.gkits = {}; S.gkitKind = "";
  if (S.kitSrc === "off") S.kitSrc = "";
  const club = p && p.cuid;
  if (club) { const r = await call("game_kits", String(club)); S.gkits = (r && r.kits) || {}; }
  if (S.kitSrc !== "manual") {
    const kind = p && p.kind === "player" ? ["home", "away", "third"].find((k) => S.gkits[k]) : "";
    if (kind) await useGameKit(kind, true);
    else if (S.kitSrc === "game") { await call("clear_kit"); S.kitSrc = ""; $("#kitImg").innerHTML = "<span>유니폼<br>사진</span>"; $("#btnKitX").hidden = true; }
  }
  renderGameKits();
}
async function useGameKit(kind, quiet) {
  const club = S.cur && S.cur.cuid;
  const r = await call("use_game_kit", String(club || ""), kind);
  if (!r || r.error) return;
  S.kitSrc = "game"; S.gkitKind = kind;
  setKitThumb(r);
  if (!quiet) toast(`게임 ${({ home: "홈", away: "원정", third: "서드" })[kind]} 유니폼을 넣었어요.`, "ok", 1800);
  renderGameKits();
}
function renderGameKits() {
  const el = $("#gameKits"), ks = Object.keys(S.gkits || {});
  const isPlayer = S.cur && S.cur.kind === "player";
  if (!ks.length) {
    el.hidden = !(isPlayer && S.cur && S.cur.cuid);
    el.innerHTML = `<span class="hint">게임에서 이 구단의 <b>구단 프로필</b> 화면을 한 번 열면 실제 유니폼을 가져와요 · 플러그인</span>`;
    return;
  }
  el.hidden = false;
  el.innerHTML = `<span class="hint">게임 유니폼</span>` + ["home", "away", "third"].filter((k) => S.gkits[k]).map((k) =>
    `<button class="chip ${S.kitSrc === "game" && S.gkitKind === k ? "on" : ""}" data-k="${k}"><img src="${S.gkits[k]}">${({ home: "홈", away: "원정", third: "서드" })[k]}</button>`).join("");
  $$("#gameKits .chip").forEach((b) => b.onclick = () => useGameKit(b.dataset.k));
}
/* 게임 유니폼 고르기 창: 모인 유니폼 전부를 구단 이름으로 검색, 아무 유니폼이나 입히기, 구단 짝 기억 */
const KIND_KO = { home: "홈", away: "원정", third: "서드" };
async function renderKitGrid() {
  const r = await call("kit_list", $("#kitQ").value.trim());
  const g = $("#kitGrid");
  if (!r || !r.items) { g.innerHTML = ""; return; }
  const cur = S.cur && S.cur.cuid ? String(S.cur.cuid) : "", curName = S.cur && S.cur.club;
  if (!r.items.length) {
    g.innerHTML = `<div class="hint" style="padding:30px;text-align:center">${$("#kitQ").value.trim() ? "찾는 구단의 유니폼이 없어요." : "아직 모인 유니폼이 없어요. 게임에서 구단 프로필을 열어 주세요 (플러그인 필요)."}</div>`;
    return;
  }
  g.innerHTML = r.items.map((x, i) => `<div class="kcard ${cur && x.club === cur ? "mine" : ""}" data-i="${i}">
      <div class="kh"><b>${esc(x.name || `유니폼 ${x.num}번`)}</b>${x.alt ? ` <span class="tg2">${esc(x.alt)}</span>` : ""}${!x.known ? ' <span class="tg2">세이브에 없는 구단 (여성팀 등)</span>' : ""}<button class="khide" title="이 유니폼 숨기기">숨기기</button>${x.user ? ' <span class="tg">직접 지정</span>' : ""}${cur && x.club === cur ? ' <span class="tg">이 선수 구단</span>' : ""}</div>
      <div class="kk">${["home", "away", "third"].filter((k) => x.kits[k]).map((k) => `<button class="kimg" data-k="${k}" title="${KIND_KO[k]} 유니폼 입히기"><img src="${x.kits[k]}"><span>${KIND_KO[k]}</span></button>`).join("")}</div>
      ${cur && x.club !== cur ? `<button class="btn sm ghost kmem">이 유니폼을 '${esc(curName || "이 선수 구단")}' 것으로 기억</button>` : ""}
    </div>`).join("") + (r.total > r.items.length ? `<div class="hint">… 외 ${r.total - r.items.length}개 · 검색해서 찾아 주세요</div>` : "");
  $("#kitNote").innerHTML = r.hidden ? `숨긴 유니폼 ${r.hidden}개 · <a id="kitUnhide">다시 보이기</a>` : "게임에서 구단 프로필을 열면 그 구단 유니폼이 여기에 모여요 (플러그인).";
  const uh = $("#kitUnhide"); if (uh) uh.onclick = async () => { await call("unhide_kits"); renderKitGrid(); };
  $$(".kcard", g).forEach((el) => {
    const x = r.items[+el.dataset.i];
    $$(".kimg", el).forEach((b) => b.onclick = async () => {
      const res = await call("use_kit_num", x.num, b.dataset.k);
      if (!res || res.error) return;
      S.kitSrc = "manual"; setKitThumb(res); renderGameKits();
      $("#kitModal").classList.remove("on");
      toast(`${x.name || "유니폼 " + x.num + "번"} ${KIND_KO[b.dataset.k]} 유니폼을 입혀요.`, "ok", 2000);
    });
    $(".khide", el).onclick = async () => { await call("hide_kit", x.num, true); toast("유니폼을 숨겼어요. 창 아래에서 다시 보이게 할 수 있어요.", "info", 2200); renderKitGrid(); };
    const m = $(".kmem", el);
    if (m) m.onclick = async () => {
      if (!await confirmBox("유니폼 기억", `이 유니폼(${x.name || "유니폼 " + x.num + "번"})을 '${curName}' 구단 것으로 기억할까요?\n다음부터 ${curName} 선수에게 자동으로 들어가요.`, "기억하기")) return;
      const res = await call("remember_kit", x.num, cur);
      if (res && res.ok) { toast(`'${curName}' 유니폼으로 기억했어요.`, "ok", 2000); await loadGameKits(S.cur); renderKitGrid(); }
    };
  });
}
let kitQT;
$("#btnKitPick").onclick = () => { $("#kitQ").value = (S.cur && S.cur.club) || ""; $("#kitModal").classList.add("on"); renderKitGrid(); setTimeout(() => $("#kitQ").select(), 50); };
$("#kitQ").addEventListener("input", () => { clearTimeout(kitQT); kitQT = setTimeout(renderKitGrid, 200); });
$("#kitX").onclick = () => $("#kitModal").classList.remove("on");
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
  rd.onload = async () => { S.kitSrc = "manual"; setKitThumb(await call("set_kit", rd.result)); renderGameKits(); };
  rd.readAsDataURL(f);
  $("#kitFile").value = "";
};
$("#btnKitX").onclick = async () => {
  await call("clear_kit");
  S.kitSrc = "off";             // 직접 뺐으면 이 사람에게는 게임 유니폼도 자동으로 안 넣는다
  renderGameKits();
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
let _qSig = null, _qTimer = 0;
function cardsFollowQueue() {
  // 대기열이 바뀌면(빼기·비우기·적용) 첫 화면 카드의 "대기 중" 사진도 맞춰 다시 그린다
  const sig = S.queue.map((q) => q.uid).sort().join(",");
  if (_qSig !== null && sig !== _qSig && S.bItems && S.bItems.length) {
    clearTimeout(_qTimer); _qTimer = setTimeout(async () => { const y = $("#bwrap").scrollTop; await doSearch(true); $("#bwrap").scrollTop = y; }, 150);
  }
  _qSig = sig;
}
function renderQueue() {
  cardsFollowQueue();
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
    if (r.conflicts && r.conflicts.length) await showConflicts(r.conflicts);
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
  const list = S.applied.filter((a) => !S.aPend.has(a.uid) && (!q || `${a.name} ${a.club} ${a.uid}`.toLowerCase().includes(q)));
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
        <button class="btn icon sm" data-edit="${a.uid}" title="다시 편집">${ico("edit")}</button>
        <button class="btn icon sm del" data-del="${a.uid}" title="이 사진 지우기">${ico("trash")}</button></div>
    </div>`).join("");
  $$(".fcard").forEach((c) => c.onclick = (e) => {
    const ed = e.target.closest("[data-edit]");
    if (ed) return editApplied(ed.dataset.edit);
    const dl = e.target.closest("[data-del]");
    if (dl) { e.stopPropagation(); return deleteLater(dl.dataset.del); }
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
/* 한 장씩 지우기 + 되돌리기 줄 (6초 뒤 실제로 지움) */
S.aPend = new Map();
const UNDO_SEC = 6;
async function deleteLater(uid) {
  const a = S.applied.find((x) => x.uid === uid);
  const r = await call("applied_remove_later", uid, UNDO_SEC);
  if (!r || !r.ok) return;
  S.aSel.delete(uid);
  const row = document.createElement("div");
  row.className = "undorow";
  row.innerHTML = `${a && a.thumb ? `<img src="${a.thumb}">` : ""}<span class="t"><b>${esc((a && a.name) || uid)}</b> 사진을 지웠어요</span><button class="btn sm">되돌리기 <span class="n">${UNDO_SEC}</span></button>`;
  $("#undoStack").appendChild(row);
  let left = UNDO_SEC;
  const tick = setInterval(() => {
    left -= 1; $(".n", row).textContent = left;
    if (left <= 0) { clearInterval(tick); finish(); }
  }, 1000);
  const finish = () => {
    row.classList.add("out"); setTimeout(() => row.remove(), 250);
    S.aPend.delete(uid);
    clearTimeout(S.aRefreshT); S.aRefreshT = setTimeout(async () => { if (!S.aPend.size) { await refreshAppliedCount(); renderApplied(); doSearch(true); } }, 900);
  };
  $("button", row).onclick = async () => {
    clearInterval(tick);
    const u = await call("applied_undo", uid);
    S.aPend.delete(uid);
    row.classList.add("out"); setTimeout(() => row.remove(), 250);
    renderApplied();
    if (u && u.ok) toast(`${(a && a.name) || uid} 사진을 되돌렸어요.`, "ok", 1800);
  };
  S.aPend.set(uid, row);
  $("#appliedCnt").textContent = S.applied.length - S.aPend.size;
  const card = document.querySelector(`.fcard[data-uid="${CSS.escape(uid)}"]`);    // 전체 다시 그리지 않고 그 카드만
  if (card) { card.style.transition = ".2s"; card.style.opacity = "0"; card.style.transform = "scale(.94)"; setTimeout(() => card.remove(), 200); }
  $("#aStat").textContent = `총 ${S.applied.length - S.aPend.size}명`;
}
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
  const b0 = $("#btnConflict"), t0 = b0.innerHTML;
  b0.disabled = true; b0.textContent = "검사 중…";
  toast("다른 페이스팩과 겹치는지 검사 중… (메가팩이 크면 몇 초 걸려요)", "info", 2500);
  const r = await call("conflict_report");
  b0.disabled = false; b0.innerHTML = t0;
  if (!r || !r.groups) return;
  const body = $("#cfBody");
  if (!r.total) body.innerHTML = `<div class="cfhead">아직 적용한 사진이 없어요.</div>`;
  else if (!r.groups.length) body.innerHTML = `<div class="cfhead ok">내 사진 ${r.total}명 중 다른 페이스팩과 겹치는 사람이 없어요.</div>`;
  else {
    body.innerHTML = `<div class="cfhead ${r.lost ? "bad" : "ok"}">내 사진 ${r.total}명 중 <b>${r.overlap}명</b>이 다른 페이스팩과 겹쳐요 · ` +
      (r.lost ? `<b>${r.lost}명은 다른 팩에 가려져요</b>` : "모두 내 사진이 이겨요") + `</div>` +
      r.groups.map((g, gi) => `<div class="cfg ${g.win ? "win" : "lose"}" data-g="${gi}">
        <div class="cfgh"><span class="res">${g.win ? "✅ 이김" : "⚠️ 짐"}</span><code>${esc(g.pack)}</code><span class="cnt">${g.items.length}명</span>
          <span class="names">${esc(g.items.slice(0, 4).map((i) => i.name).join(", "))}${g.items.length > 4 ? " …" : ""}</span>
          <button class="btn sm" data-open="${gi}">폴더 열기</button><span class="car">▾</span></div>
        <div class="cfgb" hidden></div></div>`).join("") +
      (r.lost ? `<div class="hint" style="margin-top:10px">⚠️ 진 사람은 그 폴더 이름이 우리 폴더(<code>${esc(r.ours)}</code>)보다 뒤라서 그래요. 그 폴더에서 이 사람 사진을 지우면 내 사진이 보여요.</div>` : "");
    $$(".cfg", body).forEach((el) => {
      const g = r.groups[+el.dataset.g];
      $("[data-open]", el).onclick = (e) => { e.stopPropagation(); call("open_dir", g.dir); };
      $(".cfgh", el).onclick = async () => {
        const b = $(".cfgb", el);
        b.hidden = !b.hidden; el.classList.toggle("open", !b.hidden);
        if (b.hidden || b.dataset.done) return;
        b.dataset.done = 1;
        const items = g.items.slice(0, 100);
        b.innerHTML = items.map((i, k) => `<div class="cfi" data-k="${k}"><img class="m"><span class="vs">${g.win ? "›" : "‹"}</span><img class="o"><span class="nm">${esc(i.name)}<small>${esc(i.uid)}</small></span></div>`).join("") +
          (g.items.length > 100 ? `<div class="hint">… 외 ${g.items.length - 100}명</div>` : "");
        const th = await call("thumbs", items.flatMap((i) => [i.mine, i.other])) || {};
        $$(".cfi", b).forEach((row) => { const i = items[+row.dataset.k]; $(".m", row).src = th[i.mine] || ""; $(".o", row).src = th[i.other] || ""; });
      };
    });
  }
  $("#cfModal").classList.add("on");
};
$("#cfX").onclick = () => $("#cfModal").classList.remove("on");
async function showConflicts(list) {
  // 우리 폴더보다 이름이 뒤인 페이스팩만 온다 (FM은 뒤에 읽은 폴더가 이긴다)
  const body = "아래 인물은 다른 페이스팩도 사진을 지정하고 있어요. 그 폴더가 이름순으로 우리보다 뒤에 있어서 게임에서는 그쪽 사진이 보여요.\n" +
    "내 사진을 쓰려면 그 폴더에서 이 사람 사진을 지워 주세요.\n\n" +
    list.slice(0, 12).map((c) => `• ${c.name} (${c.uid})\n   graphics\\${c.packs.join("\n   graphics\\")}`).join("\n") +
    (list.length > 12 ? `\n… 외 ${list.length - 12}명` : "");
  const dir = list[0].dirs && list[0].dirs[0];
  if (await confirmBox("다른 페이스팩에 가려져요", body, dir ? "그 폴더 열기" : "확인", false, dir ? "확인" : "닫기") && dir) call("open_dir", dir);
}

/* ------------------------------------------------------------------ 설정 */
let setAI = {}, setSel = null, setUse = null;
function openSettings(focusId) {
  const s = S.settings;
  $("#sG").value = s.graphics_dir || ""; $("#sSize").value = s.output_size || 512; $("#sTpl").value = s.prompt_template || ""; $("#sLang").value = s.prompt_lang || "ko"; $("#sUpd").checked = s.check_updates !== false; $("#sBeta").checked = !!s.beta_updates; $("#updVer").textContent = ""; $("#sPack").value = s.pack_folder || "zzz_FMFaceStudio"; packOrder();
  setAI = {};
  S.ai.forEach((a) => setAI[a.id] = { key: a.key, account: a.account, model: a.model, size: a.size || "" });
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
/* 설명 속 주소(aistudio.google.com/apikey 같은)를 누를 수 있게 */
function linkify(html) {
  return html.replace(/\b((?:[a-z0-9-]+\.)+(?:com|ai|dev)(?:\/[\w\-\/]*)?)/gi, (m) => `<a data-url="https://${m}">${m}</a>`);
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
    if (a.models && a.models.length) {
      const cur = c.model || "", known = a.models.some((m) => m.id === cur) || !cur;
      fields += `<div><span class="lbl">모델 <span class="hint">· 1장 예상 요금 (1024px)</span></span>
        <select class="msel" id="mSel">${a.models.map((m) => `<option value="${m.id}"${(cur || a.default_model) === m.id ? " selected" : ""}>${esc(m.name)} — 약 ${m.won}원</option>`).join("")}
        <option value="@custom"${known ? "" : " selected"}>직접 입력</option></select>
        <label class="field" id="mCustom" style="margin-top:6px${known ? ";display:none" : ""}"><input data-f="model" value="${esc(known ? "" : cur)}" placeholder="모델 이름"></label></div>`;
    } else
      fields += `<div><span class="lbl">모델 <span class="hint">· 비우면 기본값 ${esc(a.default_model)}</span></span><label class="field"><input data-f="model" value="${esc(c.model || "")}" placeholder="${esc(a.default_model)}"></label></div>`;
    if (a.id === "gemini") fields += `<div id="sizeRow"><span class="lbl">그림 크기 <span class="hint">· 512px는 나노 바나나 2에서만 돼요</span></span>
        <select class="msel" id="sizeSel"><option value="">1K · 기본</option><option value="512">512px · 약 65원, 조금 덜 선명</option></select></div>`;
    if (KEY_URL[a.id]) fields += `<div class="hint"><a data-url="${KEY_URL[a.id]}">발급 페이지 열기</a>${BILLING_URL[a.id] ? ` · <a data-url="${BILLING_URL[a.id]}">잔액 보기</a>` : ""}</div>`;
  }
  $("#aiDetail").innerHTML = `<h4>${esc(a.name)}<span class="tag ${tc}">${tl}</span></h4>
    <div class="muted" style="font-size:12px">${esc(a.desc)}</div>
    <ol>${(HOWTO[a.id] || []).map((t) => `<li>${linkify(esc(t))}</li>`).join("")}</ol>${fields}`;
  const zs = $("#sizeSel");
  const sizeVis = () => { const m = (setAI[a.id] && setAI[a.id].model) || c.model || a.default_model; $("#sizeRow").style.display = m === "gemini-3.1-flash-image" ? "" : "none"; };
  if (zs) {
    zs.value = c.size || "";
    zs.onchange = () => { setAI[a.id] = setAI[a.id] || {}; setAI[a.id].size = zs.value; };
    sizeVis();
  }
  const ms = $("#mSel");
  if (ms) ms.onchange = () => {
    const custom = ms.value === "@custom";
    $("#mCustom").style.display = custom ? "" : "none";
    setAI[a.id] = setAI[a.id] || {};
    setAI[a.id].model = custom ? $("#mCustom input").value : (ms.value === a.default_model ? "" : ms.value);
    if (zs) sizeVis();
  };
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
      <div class="acts">${!g.running && g.game_found && /steamapps/i.test(g.game_dir) ? `<button class="btn primary" data-act="launch">FM27 켜기</button>` : ""}${g.game_found ? `<button class="btn" data-act="gamefolder">${ico("folder")}설치 폴더</button>` : ""}<button class="btn ${g.game_found ? "" : "primary"}" data-act="setgame">${ico("folder")}${g.game_found ? "다른 폴더 지정" : "설치 폴더 지정"}</button></div>
      ${g.game_found ? "" : `<div class="note">스팀이 아닌 곳(게임패스·Xbox 앱 등)에 설치했으면 직접 지정해 주세요. 게임패스는 보통 <b>C:\\XboxGames\\Football Manager 27\\Content</b> 예요.</div>`}
      ${g.running && !g.connected ? `<div class="note">게임은 켜져 있는데 플러그인이 답하지 않아요. 플러그인이 설치돼 있는지, 세이브를 불러왔는지 확인해 주세요.</div>` : ""}`;
  } else if (popKind === "plugin") {
    const pOk = g.plugin_installed && g.plugin_up_to_date && g.bepinex;
    const diagOn = g.connected && g.heartbeat && g.heartbeat.diagnosing;
    html = `<h4><i class="${pOk ? "ok" : "warn"}"></i>${pOk ? "플러그인이 설치되어 있어요" : g.plugin_installed ? "플러그인을 업데이트해야 해요" : "플러그인이 설치되어 있지 않아요"}</h4>
      <div class="kv">${row("BepInEx", g.bepinex ? (g.bepinex_ready ? "설치됨" : "설치됨 · 게임을 한 번 켜야 준비돼요") : "없음 — 먼저 설치해 주세요", g.bepinex ? "ok" : "warn")}
        ${row("플러그인", (g.plugin_installed ? (g.plugin_up_to_date ? "설치됨 (최신)" : "예전 버전") : "없음") + (g.plugin_installed && (g.plugin_file_version || (g.heartbeat && g.heartbeat.plugin)) ? ` · ${g.plugin_file_version || g.heartbeat.plugin}` : ""), g.plugin_installed && g.plugin_up_to_date ? "ok" : "warn")}
        ${g.connected && g.heartbeat && g.heartbeat.plugin && g.plugin_file_version && g.heartbeat.plugin !== g.plugin_file_version ? row("게임 안", `아직 ${g.heartbeat.plugin} 이 돌고 있어요 — 게임을 껐다 켜 주세요`, "warn") : ""}
        ${row("게임 연결", g.connected ? "연결됨" : g.running ? "응답 없음" : "게임 꺼짐", g.connected ? "ok" : "")}
        ${row("설치 폴더", g.game_dir || "찾지 못함 — 아래에서 지정해 주세요", g.game_dir ? "dim" : "warn")}
        ${g.heartbeat && g.heartbeat.last ? row("최근 결과", g.heartbeat.last, "dim") : ""}</div>
      <div class="note">플러그인이 있으면 '한 번에 적용' 후 게임을 끄지 않아도 사진이 바로 바뀌어요.${g.bepinex ? "" : `<br><b style="color:var(--warn)">BepInEx 6 (Unity IL2CPP, win-x64, be.793 이상)</b>를 먼저 FM27 설치 폴더에 설치하고 게임을 한 번 켰다 꺼 주세요. <a data-act="bepinex">BepInEx 받는 곳</a>`}</div>
      <div style="margin-top:10px"><label class="switch"><input type="checkbox" id="optAuto" ${ST.auto_refresh ? "checked" : ""}><i></i>적용 후 게임에 자동 반영</label></div>
      <div class="acts"><button class="btn" data-act="setgame">${ico("folder")}설치 폴더 지정</button>${!pOk && g.bepinex ? `<button class="btn primary" data-act="install">${ico("upload")}${g.plugin_installed ? "플러그인 업데이트" : "플러그인 설치"}</button>` : ""}
        ${g.connected ? `<button class="btn" data-act="refresh">${ico("refresh")}지금 반영</button>` : ""}</div>
      <hr><div class="k" style="font-size:12px;color:var(--muted);font-weight:700">이미지 수집 (유니폼 연구용)</div>
      <div class="note" style="margin-top:6px">켜고 2분 동안 게임에서 구단 프로필(유니폼이 보이는 화면)을 열어 주세요. 게임이 화면에 건 그림을 모아요. 끝나면 '모은 그림 폴더'를 눌러 폴더를 압축해서 보내 주세요.</div>
      <div class="acts">${g.connected ? (g.heartbeat && g.heartbeat.collecting ? `<button class="btn" data-act="collectstop">수집 끝내기 (${g.heartbeat.collected || 0}장)</button>` : `<button class="btn" data-act="collect">이미지 수집 시작 (2분)</button>`) : `<span class="hint">게임을 켜고 세이브를 불러오면 쓸 수 있어요</span>`}<button class="btn" data-act="diagfolder">${ico("folder")}모은 그림 폴더</button></div>`;
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
  else if (act === "setgame") {
    const r = await call("pick_folder", (ST.game && ST.game.game_dir) || "");
    if (!r) return;
    const ok = await call("set_option", "game_dir", r);
    if (ok && ok.error) return toast(ok.error, "err", 6000);
    toast("FM27 설치 폴더를 지정했어요.", "ok", 2500);
    await pollStatus(); renderPop();
  }
  else if (act === "diagfolder") call("open_diag_folder");
  else if (act === "bepinex") call("open_url", ST.bepinex_url);
  else if (act === "install") {
    const g = ST.game;
    if (g.running) { toast("FM27이 켜져 있어요. 게임을 완전히 끈 다음 설치해 주세요.", "err"); return; }
    if (!await confirmBox("플러그인 설치", "FM Face Studio 플러그인을 BepInEx\\plugins 폴더에 넣어요. BepInEx와 다른 플러그인은 건드리지 않아요.\n\n게임 폴더(Program Files)에 쓰려면 관리자 권한이 필요해요. 권한 창이 뜨면 '예'를 눌러 주세요.\n\n설치할까요?", "설치")) return;
    btn.disabled = true; btn.textContent = "설치 중…";
    const r = await call("install_plugin");
    if (r && r.done) toast("설치 완료: " + r.done.join(", ") + "\n게임을 켜면 플러그인이 적용돼요.", "ok", 7000);
    pollStatus();
  } else if (act === "refresh") {
    btn.disabled = true;
    const r = await call("plugin_refresh");
    if (r) toast(r.message, r.ok ? "ok" : "err", 6000);
    pollStatus();
  } else if (act === "collect" || act === "collectstop") {
    const r = await call(act === "collect" ? "plugin_collect" : "plugin_collect_stop", 120);
    if (r) toast(r.message, r.ok ? "ok" : "err", 9000);
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
  if (st.pack_moved === "moved") toast("내 사진 폴더 이름을 zzz_FMFaceStudio로 바꿨어요.\n이제 다른 페이스팩보다 내 사진이 먼저 보여요. (게임을 켜 놨다면 한 번 껐다 켜 주세요)", "ok", 8000);
  else if (st.pack_moved === "failed") toast("내 사진 폴더 이름을 바꾸지 못했어요. FM27을 끄고 프로그램을 다시 켜 주세요.", "err", 8000);
  setTimeout(() => checkUpdate(false), 200);
})();

/* ------------------------------------------------------------------ 자동 업데이트 */
let UPD = null;
async function checkUpdate(manual) {
  const r = await call("check_update", manual);
  if (!r) return;
  if (manual) $("#updVer").textContent = r.version ? `지금 ${r.current} · 최신 ${r.label || r.version}` : (r.error || "");
  if (r.available) {
    UPD = r;
    $("#updText").textContent = `새 버전 ${r.label || r.version}이 나왔어요 (지금 ${r.current})`;
    $("#updBar").hidden = false;
  } else if (manual) toast(r.error || "최신 버전을 쓰고 있어요.", r.error ? "err" : "ok", 2500);
}
$("#updX").onclick = () => { $("#updBar").hidden = true; };
$("#updSkip").onclick = async () => { if (UPD) await call("set_option", "skip_version", UPD.version); $("#updBar").hidden = true; };
$("#updNotes").onclick = () => { if (UPD) confirmBox(`새 버전 ${UPD.version}`, (UPD.notes || "바뀐 점이 적혀 있지 않아요.").replace(/\*\*|`/g, ""), "지금 업데이트").then((ok) => ok && $("#updGo").click()); };
$("#updGo").onclick = async () => {
  if (S.queue.length && !await confirmBox("업데이트", `대기열에 ${S.queue.length}명이 있어요. 대기열은 그대로 남아 있으니 업데이트 뒤에 이어서 하면 돼요.\n\n업데이트할까요?`, "업데이트")) return;
  $("#updBar").hidden = true;
  $("#updModal").classList.add("on");
  $("#updMsg").textContent = `새 버전 ${UPD.version} 받는 중…`; $("#updFill").style.width = "0%"; $("#updSub").textContent = "";
  const t = setInterval(async () => {
    const p = await API.progress();
    if (p && p.total) { const pc = Math.floor(p.done / p.total * 100); $("#updFill").style.width = pc + "%"; $("#updSub").textContent = `${(p.done / 1048576).toFixed(0)} / ${(p.total / 1048576).toFixed(0)} MB · ${pc}%`; }
  }, 400);
  const r = await call("do_update");
  clearInterval(t);
  if (r && r.ok) { $("#updFill").style.width = "100%"; $("#updMsg").textContent = "다 받았어요. 설치를 시작해요"; $("#updSub").textContent = "프로그램이 잠깐 꺼졌다가 설치가 끝나면 다시 켜져요 (10~20초)"; }
  else $("#updModal").classList.remove("on");
};
async function packOrder() {
  const r = await call("pack_folder_info");
  if (!r || !r.folders) return;
  const i = r.folders.indexOf(r.name), n = r.folders.length;
  const after = i >= 0 ? r.folders.slice(i + 1) : [];
  $("#packOrder").textContent = i < 0 ? "FM은 graphics 안 폴더를 이름순으로 읽고, 뒤에 오는 폴더가 이겨요."
    : after.length ? `지금 ${n}개 폴더 중 ${i + 1}번째예요. 뒤에 있는 ${after.slice(0, 3).join(", ")}${after.length > 3 ? " 등" : ""}은(는) 내 사진을 이길 수 있어요.`
    : `지금 ${n}개 폴더 중 맨 뒤라서 다른 페이스팩보다 내 사진이 보여요.`;
}
$("#btnPack").onclick = async () => {
  const v = $("#sPack").value.trim();
  if (!await confirmBox("폴더 이름 바꾸기", `내 사진 폴더 이름을 '${v || "zzz_FMFaceStudio"}'(으)로 바꿀까요?\n안의 사진도 함께 옮겨져요. 게임은 꺼 두는 게 좋아요.\n\n이름순으로 뒤에 올수록 다른 페이스팩을 이겨요.`, "바꾸기")) return;
  const r = await call("rename_pack_folder", v);
  if (r && r.ok) { S.settings.pack_folder = r.name; $("#sPack").value = r.name; toast(`폴더 이름을 ${r.name}(으)로 바꿨어요. FM27을 껐다 켜면 반영돼요.`, "ok", 4500); packOrder(); }
};
$("#btnUpdNow").onclick = () => checkUpdate(true);
$("#sUpd").onchange = (e) => call("set_option", "check_updates", e.target.checked);
$("#sBeta").onchange = async (e) => { await call("set_option", "beta_updates", e.target.checked); if (e.target.checked) checkUpdate(true); };


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

$("#btnReport").onclick = async () => {
  const r = await call("make_report");
  if (r && r.ok) confirmBox("오류 보고 파일을 만들었어요", `${r.path}\n\n이 파일을 개발자에게 보내 주세요. 에펨코리아에서 'FM Face Studio' 글쓴이에게 쪽지로 문의하시면 받을 곳을 알려 드려요.\n(API 키 같은 개인 정보는 들어 있지 않아요)`, "확인", false, "닫기");
};


/* ------------------------------------------------------------------ 카드에 사진 끌어다 놓기 */
function fileToDataUrl(f) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
}
function bindCardDrop(c) {
  let depth = 0;
  const has = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  c.addEventListener("dragenter", (e) => { if (!has(e)) return; e.preventDefault(); depth++; c.classList.add("dropon"); });
  c.addEventListener("dragover", (e) => { if (!has(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
  c.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; c.classList.remove("dropon"); } });
  c.addEventListener("drop", async (e) => {
    if (!has(e)) return;
    e.preventDefault(); e.stopPropagation();
    depth = 0; c.classList.remove("dropon");
    const f = Array.from(e.dataTransfer.files).find((x) => /^image\//.test(x.type) || /\.(png|jpe?g|webp|bmp|gif)$/i.test(x.name));
    if (!f) { toast("사진 파일만 놓을 수 있어요.", "err"); return; }
    const p = S.bItems[+c.dataset.i];
    if (!p) return;
    c.classList.add("dropbusy");
    const r = await call("quick_add", p, await fileToDataUrl(f));
    c.classList.remove("dropbusy");
    if (!r || r.error) return;
    S.queue = r.queue; renderQueue();
    p.queued = true; p.face = r.thumb;
    const img = $(".ph2", c);
    img.innerHTML = `<img src="${r.thumb}"><div class="dropcue">사진을 놓으면<br>바로 대기열에</div>`;
    const t = $(".tag", c); if (t) { t.className = "tag queued"; t.textContent = "대기 중"; }
    c.classList.add("flash"); setTimeout(() => c.classList.remove("flash"), 900);
    toast(`${p.name} 사진을 대기열에 넣었어요. 얼굴 맞춤으로 자동으로 잘랐어요.\n손볼 건 카드를 눌러 편집하세요.`, "ok", 3500);
  });
}



/* ------------------------------------------------------------------ 대량으로 바꾸기 */
S.bulk = [];
const IMG_RE = /\.(png|jpe?g|webp|bmp|gif)$/i;
function candLabel(c) {
  if (!c.name) return `UID ${c.uid} (세이브에 없음)`;
  return `${c.name} · ${c.club || "무소속"}${c.alt ? " (" + c.alt + ")" : ""}${c.age ? " · " + c.age + "세" : ""}${c.me ? " · 내 감독" : ""}`;
}
function decoSummary() {
  const d = S.deco || {}, out = [];
  if (d.caption) out.push(`이름 띠(${({ gold: "금색", white: "흰색", navy: "남색" })[d.style] || d.style})`);
  if (d.rounded) out.push("둥근 모서리");
  if (d.border) out.push("테두리");
  return out.length ? out.join(" · ") : "꾸미기 없음";
}
function renderBulkOpts() {
  const st = S.settings || {}, crop = st.bulk_crop || "face", deco = st.bulk_deco || "none";
  $$("#bCrop button").forEach((b) => b.classList.toggle("on", b.dataset.v === crop));
  $$("#bDeco button").forEach((b) => b.classList.toggle("on", b.dataset.v === deco));
  $("#bOptSum").textContent = (crop === "face" ? "얼굴을 찾아 가운데로" : "사진 구도 그대로 (세로 사진은 위쪽 맞춤)") +
    " · " + (deco === "follow" ? "편집 화면 꾸미기: " + decoSummary() : "꾸미기 없이 사진만");
}
$$("#bCrop button").forEach((b) => b.onclick = () => { S.settings.bulk_crop = b.dataset.v; call("set_option", "bulk_crop", b.dataset.v); renderBulkOpts(); });
$$("#bDeco button").forEach((b) => b.onclick = () => { S.settings.bulk_deco = b.dataset.v; call("set_option", "bulk_deco", b.dataset.v); renderBulkOpts(); });
function openBulk(files) {
  renderBulkOpts();
  $("#bulkModal").classList.add("on");
  if (files && files.length) bulkFromFiles(files);
  else if (!S.bulk.length) { $("#bulkHelp").hidden = false; $("#bulkTable").hidden = true; renderBulkSum(); }
}
async function bulkFromFiles(files) {
  files = files.filter((f) => IMG_RE.test(f.name));
  if (!files.length) { toast("사진 파일이 없어요.", "err"); return; }
  const r = await call("bulk_match", files.map((f) => f.name));
  if (!r) return;
  if (!r.loaded) toast("세이브를 아직 안 읽어서 이름으로는 못 찾아요. 고유번호 파일만 연결돼요.", "info", 5000);
  S.bulk = r.rows.map((row, i) => ({ ...row, fileObj: files[i], thumb: URL.createObjectURL(files[i]) }));
  S.bulkFolder = ""; initPicks(); renderBulk();
}
async function bulkFromFolder() {
  const r = await call("bulk_pick_folder");
  if (!r || r.cancel) return;
  if (!r.rows.length) { toast("그 폴더에 사진 파일이 없어요.", "err"); return; }
  if (!r.loaded) toast("세이브를 아직 안 읽어서 이름으로는 못 찾아요. 고유번호 파일만 연결돼요.", "info", 5000);
  S.bulk = r.rows; S.bulkFolder = r.folder || ""; initPicks(); renderBulk();
}
async function bulkRescan() {
  // 파일 이름을 고친 뒤: 같은 폴더를 다시 읽는다 (끌어다 놓은 사진은 다시 끌어다 놓아야 새 이름이 보여요)
  if (S.bulkFolder) {
    const r = await call("bulk_scan", S.bulkFolder);
    if (!r || r.error) return;
    S.bulk = r.rows; initPicks(); renderBulk();
    toast(`폴더를 다시 읽었어요 (사진 ${r.rows.length}장).`, "ok", 2000);
  } else if (S.bulk.length) {
    const r = await call("bulk_match", S.bulk.map((x) => x.file));
    if (!r) return;
    S.bulk = S.bulk.map((x, i) => ({ ...x, ...r.rows[i] })); initPicks(); renderBulk();
    toast("다시 짝지었어요. 파일 이름을 고쳤다면 사진을 다시 끌어다 놓아 주세요.", "info", 3500);
  }
}
function bulkReset() {
  S.bulk = []; S.bulkFolder = "";
  $("#bulkHelp").hidden = false; $("#bulkTable").hidden = true; $("#bulkNote").textContent = "위에서 고른 자르기·꾸미기는 첫 화면 카드에 사진을 끌어다 놓을 때도 똑같이 쓰여요.";
  renderBulkSum();
}
function initPicks() {
  // 같은 이름 파일이 여러 장이면(김민재.png, 김민재 (2).png) 후보를 겹치지 않게 차례로 나눠 준다
  const used = {};
  S.bulk.forEach((row) => {
    row.manual = ""; row.done = false;
    if (!row.candidates.length) { row.pick = ""; return; }
    const k = row.key || row.file, n = used[k] || 0;
    row.pick = n < row.candidates.length ? row.candidates[n].uid : "";
    used[k] = n + 1;
  });
}
function dupPicks() {
  const c = {};
  S.bulk.forEach((r) => { const u = r.pick === "@manual" ? r.manual.trim() : r.pick; if (u && !r.done) c[u] = (c[u] || 0) + 1; });
  return c;
}
function rowStatus(row, dups) {
  if (row.done) return ["done", "대기열에 넣음"];
  const u = row.pick === "@manual" ? row.manual.trim() : row.pick;
  if (u && (dups || dupPicks())[u] > 1) return ["none", "같은 사람이 두 번 골라졌어요"];
  if (row.pick === "") return row.status === "none" ? ["none", "못 찾음"] : ["skip", "건너뛰기"];
  if (row.pick === "@manual") return row.manual.trim() ? ["ok", "직접 입력"] : ["none", "UID를 넣어 주세요"];
  if (row.status === "multi") return ["multi", `동명이인 ${row.candidates.length}명 · 확인`];
  if (row.status === "multi" && row.how === "order") return ["multi", "이름 순서가 달라요 · 확인"];
  return ["ok", "찾음"];
}
function renderBulk() {
  $("#bulkHelp").hidden = true; $("#bulkTable").hidden = false;
  const dups = dupPicks();
  const rows = S.bulk.map((row, i) => {
    const [cls, txt] = rowStatus(row, dups);
    const opts = row.candidates.map((c) => `<option value="${esc(c.uid)}" ${row.pick === c.uid ? "selected" : ""}>${esc(candLabel(c))}</option>`).join("")
      + `<option value="@manual" ${row.pick === "@manual" ? "selected" : ""}>UID 직접 입력…</option><option value="" ${row.pick === "" ? "selected" : ""}>— 건너뛰기 —</option>`;
    return `<tr data-i="${i}"><td>${row.thumb ? `<img src="${row.thumb}">` : ""}</td><td class="fn" title="${esc(row.file)}">${esc(row.file)}</td>
      <td><select class="bpick" ${row.done ? "disabled" : ""}>${opts}</select>${row.pick === "@manual" ? `<input class="bman" placeholder="예: r-2002097354" value="${esc(row.manual)}" style="margin-top:4px">` : ""}</td>
      <td><span class="st ${cls}">${txt}</span></td></tr>`;
  }).join("");
  $("#bulkTable").innerHTML = `<table><thead><tr><th></th><th>파일</th><th>연결할 사람</th><th>상태</th></tr></thead><tbody>${rows}</tbody></table>`;
  $$("#bulkTable tr[data-i]").forEach((tr) => {
    const row = S.bulk[+tr.dataset.i];
    $(".bpick", tr).onchange = (e) => { row.pick = e.target.value; if (row.status === "multi" && row.pick && row.pick !== "@manual") row.status = "ok"; renderBulk(); };
    const m = $(".bman", tr); if (m) m.oninput = (e) => { row.manual = e.target.value; renderBulkSum(); refreshBulkStatus(); };
  });
  renderBulkSum();
}
function refreshBulkStatus() {
  const d = dupPicks();
  $$("#bulkTable tr[data-i]").forEach((tr) => { const [c, t] = rowStatus(S.bulk[+tr.dataset.i], d); const st = $(".st", tr); st.className = "st " + c; st.textContent = t; });
}
function bulkTargets() {
  return S.bulk.filter((r) => !r.done && r.pick && (r.pick !== "@manual" || r.manual.trim()));
}
function renderBulkSum() {
  const n = S.bulk.length, go = bulkTargets().length;
  const multi = S.bulk.filter((r) => !r.done && r.status === "multi" && r.pick).length;
  const none = S.bulk.filter((r) => rowStatus(r)[0] === "none").length;
  $("#bulkSum").textContent = n ? `사진 ${n}장 · 넣을 사람 ${go}명${multi ? ` · 확인 필요 ${multi}` : ""}${none ? ` · 못 찾음 ${none}` : ""}` : "";
  $("#bulkGo").disabled = !go;
  ["#bulkRepick", "#bulkRescan", "#bulkReset"].forEach((k) => { $(k).hidden = !n; });
  $("#bulkGo").textContent = go ? `${go}명 대기열에 넣기` : "대기열에 넣기";
}
$("#btnBulk").onclick = () => openBulk();
$("#bulkFolder").onclick = bulkFromFolder;
$("#bulkRepick").onclick = bulkFromFolder;
$("#bulkRescan").onclick = bulkRescan;
$("#bulkReset").onclick = bulkReset;
$("#bulkClose").onclick = () => $("#bulkModal").classList.remove("on");
$("#bulkGo").onclick = async () => {
  const list = bulkTargets();
  if (Object.values(dupPicks()).some((n) => n > 1)) { toast("같은 사람이 두 번 골라진 줄이 있어요. 빨간 줄을 고쳐 주세요.", "err", 3500); return; }
  const multi = list.filter((r) => r.status === "multi").length;
  if (multi && !await confirmBox("동명이인 확인", `동명이인(또는 이름 순서가 다른) 사진이 ${multi}장 있어요. 노란 줄을 확인했나요?\n\n그대로 넣을까요?`, "그대로 넣기")) return;
  $("#bulkGo").disabled = true;
  let ok = 0;
  for (const [k, row] of list.entries()) {
    $("#bulkNote").textContent = `넣는 중… ${k + 1} / ${list.length}  (${row.file})`;
    const person = row.pick === "@manual" ? { uid: row.manual.trim(), name: "", kind: S.kind === "manager" ? "staff" : S.kind, newgen: /^r-/i.test(row.manual.trim()) }
      : row.candidates.find((c) => c.uid === row.pick);
    const data = row.fileObj ? await fileToDataUrl(row.fileObj) : "";
    const r = await call("bulk_add_one", person, row.path || "", data);
    if (r && r.ok) { row.done = true; ok++; }
  }
  $("#bulkNote").textContent = `${ok}명을 대기열에 넣었어요. 오른쪽 '한 번에 적용'을 누르면 게임에 들어가요.`;
  const q = await call("queue_view"); if (q) { S.queue = q.queue; renderQueue(); }
  renderBulk(); doSearch(true);
  toast(`${ok}명을 대기열에 넣었어요.`, "ok", 3000);
};
(function bulkDrop() {
  const dlg = $(".dlg.bulk");
  dlg.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); dlg.classList.add("dropon"); });
  dlg.addEventListener("dragleave", (e) => { if (!dlg.contains(e.relatedTarget)) dlg.classList.remove("dropon"); });
  dlg.addEventListener("drop", (e) => {
    e.preventDefault(); e.stopPropagation(); dlg.classList.remove("dropon");
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) bulkFromFiles(files);
  });
})();

/* ================================================================ AI로 한꺼번에 그리기 */
const AB = { banner: "none", people: [], sel: new Set(), task: "face", kitKind: "home", thumbs: {}, ver: {}, items: [], pick: new Set(), timer: 0, running: false, price: null, big: null };
const AB_ENG = ["local", "gemini", "openai", "xai", "codex", "cloudflare"];
const AB_TASK_HINT = { face: "게임 외모 설명(피부·머리)으로 새 얼굴을 그려요.", kit: "지금 사진의 얼굴은 두고 옷만 바꿔요. 지금 사진이 있는 사람만 돼요.", gunzo: "경기장에서 뛰는 모습을 그려요. 얼굴 참고를 켜면 지금 얼굴로 그려요." };
const AB_BANNER_HINT = { follow: "편집 화면의 꾸미기(이름띠·모서리·테두리) 그대로", none: "사진만 넣어요. 꾸미기는 나중에 더할 수 있어요" };
const won = (n) => Math.round(n).toLocaleString("ko-KR");

async function openAB() {
  $("#abModal").classList.add("on");
  const st = await call("batch_status");
  if (st && st.items.length) { showABRun(st); return; }
  showABSetup();
}
async function showABSetup() {
  stopABPoll();
  $("#abSetup").hidden = false; $("#abRun").hidden = true;
  ["#abNew", "#abStop", "#abResume", "#abSelAll", "#abQueue"].forEach((k) => $(k).hidden = true);
  $("#abGo").hidden = false;
  renderABEngines();
  renderABOpts();
  $("#abPeople").innerHTML = `<div class="empty" style="grid-column:1/-1;padding:30px"><div><div class="spin"></div>목록을 모으는 중…</div></div>`;
  const n = $("#qName").value.trim(), t = $("#qTeam").value.trim();
  const club = S.teamClub && S.teamClub.name === t ? S.teamClub.cuid : "";
  const r = await call("batch_people", n, t, S.kind, S.filter, S.kind === "player" ? S.squad : "", club);
  if (!r) return;
  AB.people = r.items;
  AB.sel = new Set();          // 처음엔 아무도 안 고른 채로 (실수로 많이 그리지 않게)
  AB.total = r.total; AB.max = r.max;
  renderABPeople();
}
function renderABEngines() {
  const sel = $("#abEngine"), cur = sel.value || "local";     // 기본은 내 PC 그림도구 (무료)
  sel.innerHTML = AB_ENG.map((id) => {
    const a = S.ai.find((x) => x.id === id); if (!a) return "";
    return `<option value="${id}">${esc(a.name)} · ${esc(a.status)}</option>`;
  }).join("");
  sel.value = cur;
  abPrice();
}
async function abPrice() {
  const eng = $("#abEngine").value;
  AB.price = await call("batch_price", eng);
  $("#abLocal").hidden = eng !== "local";
  $("#abCost").hidden = eng === "local";
  if (eng === "local") loadDT(true);
  renderABCost();
}
/* ---------------- 내 PC 그림도구 (설치·지우기) */
let DT = null, dtTimer = 0;
const gb = (b) => (b / 1e9).toFixed(b >= 1e10 ? 0 : 1);
async function loadDT(gpu) {
  const r = await call("drawtool_status", !!gpu);
  if (!r) return;
  DT = r; renderDT();
  clearTimeout(dtTimer);
  if (r.task && r.task.active && $("#abModal").classList.contains("on")) dtTimer = setTimeout(() => loadDT(false), 1500);
}
function renderDT() {
  const el = $("#abLocal"), d = DT; if (!d) return;
  const g = d.gpu || {}, t = d.task || {};
  const gpuTxt = g.ok ? `<span class="gpu ok">✓ ${esc(g.name)} · ${g.vram}GB</span>${g.tight ? ' <span class="hint">메모리가 빠듯해서 조금 느릴 수 있어요</span>' : ""}` : `<span class="gpu no">✕ ${esc(g.reason || "그래픽카드를 확인하지 못했어요")}</span>`;
  let h = `<div class="lrow"><b>그래픽카드</b>${gpuTxt}</div>`;
  if (t.active) {
    const pct = t.total ? Math.min(99, Math.round(t.done / t.total * 100)) : 0;
    h += `<div class="lrow"><b>설치 중</b><span>${esc(t.step || "")}</span></div>
      <div class="abprog"><div class="abbar"><i style="width:${pct}%"></i></div><span>${t.files ? `파일 ${t.files[0]}/${t.files[1]} · ` : ""}${gb(t.done)} / 약 ${gb(t.total)}GB</span></div>
      ${t.last ? `<div class="hint" style="font-family:Consolas,monospace;font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.last)}</div>` : ""}
      <div class="lrow"><span class="hint grow">이 창을 닫아도 설치는 계속돼요. 큰 파일은 한동안 멈춘 것처럼 보일 수 있어요.</span><button class="btn sm" id="dtLog">설치 기록</button><button class="btn sm" id="dtCancel">설치 취소</button></div>`;
  } else if (d.installed) {
    h += `<div class="lrow"><b>설치됨</b><code>${esc(d.root)}</code><span class="hint">쓰는 용량 약 ${gb(d.used || 0)}GB</span></div>`;
    h += Object.entries(d.models).map(([k, m]) => `<div class="mrow">${m.installed ? '<span class="done">✓ 받음</span>' : `<button class="btn sm" data-add="${k}">추가로 받기</button>`}<span>${esc(m.name)}</span><span class="sz">약 ${gb(m.size)}GB</span></div>`).join("");
    h += `<div class="lrow"><span class="hint grow">요금 없이 내 그래픽카드로 그려요. 첫 장은 그림도구를 켜느라 1~2분 더 걸려요.</span><button class="btn sm" id="dtLog">설치 기록</button><button class="btn sm" id="dtDel">그림도구 지우기</button></div>`;
  } else {
    const adv = $("#dtAdv") ? $("#dtAdv").checked : false;
    const need = d.pkg_est + d.models.std.size + (adv ? d.models.adv.size : 0);
    h += `<div class="lrow"><b>설치 폴더</b><code>${esc(d.root)}</code><button class="btn sm" id="dtDir">폴더 바꾸기</button></div>
      <div class="mrow"><span class="done">✓ 필수</span><span>${esc(d.models.std.name)}</span><span class="sz">약 ${gb(d.models.std.size)}GB · 얼굴·유니폼 참고 가능</span></div>
      <div class="mrow"><label class="switch"><input type="checkbox" id="dtAdv"${adv ? " checked" : ""}><i></i>${esc(d.models.adv.name)}</label><span class="sz">약 ${gb(d.models.adv.size)}GB · 사진 느낌 더 좋음, 글로만 그림 (선택)</span></div>
      <div class="lrow"><span>받는 용량 약 <b>${gb(need)}GB</b> · 남은 공간 ${gb(d.free)}GB</span>${d.free < need * 1.1 + 2e9 ? '<span class="gpu no">공간이 모자라요. 폴더를 다른 드라이브로 바꿔 주세요.</span>' : ""}<span class="hint">프로그램(파이썬·PyTorch 약 ${gb(d.pkg_est)}GB) 포함</span></div>
      ${t.error ? `<div class="err">지난 설치가 멈췄어요: ${esc(t.error)}</div>` : ""}
      <div class="lrow"><span class="hint grow">인터넷 속도에 따라 수십 분 걸려요. 중간에 끊겨도 다시 누르면 이어서 받아요.</span>${t.error ? '<button class="btn sm" id="dtLog">설치 기록</button>' : ""}<button class="btn primary" id="dtGo"${g.ok && d.free >= need * 1.1 + 2e9 ? "" : " disabled"}>그림도구 설치</button></div>`;
  }
  el.innerHTML = h;
  const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  on("#dtCancel", async () => { await call("drawtool_cancel"); toast("설치를 멈추는 중이에요.", "info", 2000); setTimeout(() => loadDT(false), 1200); });
  on("#dtDir", async () => { const r = await call("drawtool_pick_dir"); if (r && !r.cancel) { DT = r; renderDT(); } });
  on("#dtLog", () => call("drawtool_open_log"));
  const adv = $("#dtAdv"); if (adv) adv.onchange = renderDT;
  on("#dtGo", async () => {
    const keys = ["std"].concat($("#dtAdv").checked ? ["adv"] : []);
    const r = await call("drawtool_install", keys);
    if (r && r.error) { toast(r.error, "err", 4500); return; }
    if (r) { DT = r; renderDT(); loadDT(false); }
  });
  $$("#abLocal [data-add]").forEach((b) => b.onclick = async () => {
    const r = await call("drawtool_install", [b.dataset.add]);
    if (r && r.error) { toast(r.error, "err", 4500); return; }
    if (r) { DT = r; renderDT(); loadDT(false); }
  });
  on("#dtDel", async () => {
    if (!await confirmBox("그림도구 지우기", `그림도구 폴더를 통째로 지워요.\n${d.root}\n\n약 ${gb(d.used || 0)}GB가 비워져요. 다시 쓰려면 처음부터 받아야 해요.`, "지우기", true)) return;
    busy(true, "그림도구 지우는 중…");
    const r = await call("drawtool_uninstall");
    busy(false);
    if (r && r.error) { toast(r.error, "err", 4000); return; }
    if (r) toast(`그림도구를 지웠어요. 약 ${gb(r.freed || 0)}GB를 비웠어요.${r.left ? " (일부 파일은 남았어요)" : ""}`, "ok", 4000);
    loadDT(false); renderABEngines();
  });
  if (!t.active && t.finished && !t.error && !DT._toasted) { DT._toasted = true; }
}
function renderABOpts() {
  $$("#abTask button").forEach((b) => b.classList.toggle("on", b.dataset.v === AB.task));
  $$("#abKitKind button").forEach((b) => b.classList.toggle("on", b.dataset.v === AB.kitKind));
  $("#abTaskHint").textContent = AB_TASK_HINT[AB.task] || "";
  $("#abRefRow").style.display = AB.task !== "kit" ? "" : "none";
  $$(".gzrow").forEach((r) => r.style.display = AB.task === "gunzo" ? "" : "none");
  $$("#abBanner button").forEach((b) => b.classList.toggle("on", b.dataset.v === AB.banner));
  $("#abBannerHint").textContent = AB_BANNER_HINT[AB.banner];
  $("#abKitKind").style.opacity = $("#abKit").checked ? 1 : .4;
  renderABCost();
}
function abTargets() {
  return AB.people.filter((p) => AB.sel.has(p.uid) && (AB.task !== "kit" || p.has_face));
}
function renderABCost() {
  const el = $("#abCost"), pr = AB.price, n = abTargets().length;
  if (!pr) { el.textContent = ""; return; }
  el.classList.toggle("free", pr.kind !== "paid");
  const eng = $("#abEngine").value, a = S.ai.find((x) => x.id === eng) || {};
  let warn = "";
  if (!pr.ready) warn = ` <a id="abKey">${esc(a.name)} 연결 정보 넣기</a>`;
  if (pr.kind === "free") el.innerHTML = `무료 사용량 안에서 그려요 (하루 한도가 있어요). 참고 사진은 못 보내서 <b>유니폼·지금 사진 참고가 빠져요</b>.${warn}`;
  else if (pr.kind === "sub") el.innerHTML = `ChatGPT 구독 사용량으로 그려요. 많이 그리면 한도에 걸릴 수 있어요.${warn}`;
  else el.innerHTML = `1장 약 <b>${won(pr.won)}원</b> × ${n}명 = 약 <b>${won(pr.won * n)}원</b> <span class="hint">(${esc(pr.model)} · 예상값이에요. 다시 그리면 그만큼 더 나가요)</span>${warn}${BILLING_URL[eng] ? ` <a class="billink" data-url="${BILLING_URL[eng]}">잔액 보기</a>` : ""}`;
  $$("#abCost [data-url]").forEach((l) => l.onclick = () => call("open_url", l.dataset.url));
  const k = $("#abKey"); if (k) k.onclick = () => { $("#abModal").classList.remove("on"); openSettings(eng); };
  $("#abGo").disabled = !n;
  $("#abGo").textContent = n ? `${n}명 그리기 시작` : "그리기 시작";
}
function renderABPeople() {
  const g = $("#abPeople");
  if (!AB.people.length) { g.innerHTML = `<div class="empty" style="grid-column:1/-1;padding:30px">지금 목록에 사람이 없어요. 첫 화면에서 이름·팀·필터로 먼저 골라 주세요.</div>`; renderABSum(); return; }
  g.innerHTML = AB.people.map((p, i) => {
    const off = AB.task === "kit" && !p.has_face;
    return `<div class="abp${AB.sel.has(p.uid) && !off ? " on" : ""}" data-i="${i}" style="${off ? "opacity:.35" : ""}" title="${off ? "지금 사진이 없어서 유니폼만 바꾸기를 못 해요" : ""}">
      <span class="ck"></span>${p.game_face ? '<span class="tg" title="사진이 없어 게임 얼굴을 참고해요 (참고 켰을 때)">게임 얼굴</span>' : p.kits ? '<span class="tg">유니폼</span>' : ""}
      <div class="im">${p.face ? `<img src="${p.face}">` : "사진 없음"}</div>
      <div class="nm">${esc(p.name)}</div><div class="sb">${esc(p.club || "무소속")}${p.age ? " · " + esc(p.age) : ""}</div></div>`;
  }).join("");
  $$(".abp", g).forEach((c) => c.onclick = () => {
    const p = AB.people[+c.dataset.i];
    if (AB.task === "kit" && !p.has_face) return;
    AB.sel.has(p.uid) ? AB.sel.delete(p.uid) : AB.sel.add(p.uid);
    c.classList.toggle("on", AB.sel.has(p.uid));
    renderABSum();
  });
  renderABSum();
}
function renderABSum() {
  const n = abTargets().length;
  $("#abPickSum").textContent = `지금 목록 ${AB.people.length}명 중 ${n}명${AB.total > AB.max ? ` · 목록이 ${AB.total.toLocaleString()}명이라 앞 ${AB.max}명만 보여요` : ""}`;
  renderABCost();
}
$$("#abTask button").forEach((b) => b.onclick = () => { if (b.disabled) return; AB.task = b.dataset.v; renderABOpts(); renderABPeople(); });
$$("#abKitKind button").forEach((b) => b.onclick = () => { AB.kitKind = b.dataset.v; renderABOpts(); });
$$("#abBanner button").forEach((b) => b.onclick = () => { AB.banner = b.dataset.v; renderABOpts(); });
$("#abKit").onchange = renderABOpts;
$("#abEngine").onchange = abPrice;
$("#abAll").onclick = () => { AB.sel = new Set(AB.people.map((p) => p.uid)); renderABPeople(); };
$("#abNone").onclick = () => { AB.sel.clear(); renderABPeople(); };
$("#abNoFace").onclick = () => { AB.sel = new Set(AB.people.filter((p) => !p.has_face).map((p) => p.uid)); renderABPeople(); };
$("#btnAB").onclick = openAB;
$("#btnRefresh").onclick = () => { doSearch(false); toast("목록을 다시 읽었어요.", "ok", 1500); };
$("#abRefresh").onclick = async () => {
  const keep = new Set(AB.sel), old = new Set(AB.people.map((p) => p.uid));
  await showABSetup();
  AB.sel = new Set(AB.people.filter((p) => keep.has(p.uid) || !old.has(p.uid)).map((p) => p.uid));
  renderABPeople();
};
$("#abClose").onclick = () => { $("#abModal").classList.remove("on"); stopABPoll(); };
$("#abGo").onclick = async () => {
  const list = abTargets(), pr = AB.price || {};
  if (!list.length) return;
  if (pr.kind === "paid" && !await confirmBox("요금 확인", `${list.length}명을 그려요. 예상 요금은 약 ${won(pr.won * list.length)}원이에요.\n\n요금은 API 키에 연결한 결제에서 빠져나가요. 시작할까요?`, "시작")) return;
  const r = await call("batch_start", list, AB.task, { engine: $("#abEngine").value, kit_kind: AB.kitKind, use_kit: $("#abKit").checked, ref: $("#abRef").checked, extra: $("#abExtra").value, action: $("#abAction").value, banner: AB.banner });
  if (!r) return;
  if (r.error === "need_key") { toast("연결 정보가 없어요. 설정에서 넣어 주세요.", "err"); $("#abModal").classList.remove("on"); openSettings(r.engine); return; }
  if (r.skipped) toast(`지금 사진이 없는 ${r.skipped}명은 빼고 그려요.`, "info", 3500);
  AB.thumbs = {}; AB.ver = {}; AB.pick.clear();
  showABRun(await call("batch_status"));
};

function showABRun(st) {
  $("#abSetup").hidden = true; $("#abRun").hidden = false; $("#abGo").hidden = true;
  ["#abNew", "#abSelAll", "#abQueue"].forEach((k) => $(k).hidden = false);
  renderABRun(st);
  startABPoll();
}
function startABPoll() { stopABPoll(); AB.timer = setInterval(pollAB, 1500); }
function stopABPoll() { if (AB.timer) clearInterval(AB.timer); AB.timer = 0; }
async function pollAB() {
  if (!$("#abModal").classList.contains("on")) { stopABPoll(); return; }
  const st = await call("batch_status");
  if (st) renderABRun(st);
  if (st && !st.running) stopABPoll();
}
async function renderABRun(st) {
  AB.items = st.items; AB.running = st.running;
  const need = st.items.filter((i) => i.ver && AB.ver[i.id] !== i.ver).map((i) => i.id);
  if (need.length) {
    const r = await call("batch_thumbs", need);
    if (r) for (const [k, v] of Object.entries(r.thumbs)) { AB.thumbs[k] = v; AB.ver[k] = st.items.find((i) => i.id === k).ver; }
  }
  const ids = new Set(st.items.map((i) => i.id));
  [...AB.pick].forEach((k) => { if (!ids.has(k)) AB.pick.delete(k); });
  const c = st.counts, tot = st.items.length, fin = c.done + c.fail;
  $("#abFill").style.width = tot ? `${fin / tot * 100}%` : "0";
  const task = { face: "새 얼굴", kit: "유니폼만 바꾸기", gunzo: "건조" }[st.meta.task] || "";
  const warm = st.meta.local_state === "loading" ? " · 그림도구 켜는 중 (처음 1~2분)" : "";
  const spent = st.meta.won && st.meta.spent ? ` · 이번에 ${st.meta.spent}장, 약 ${won(st.meta.won * st.meta.spent)}원` : "";
  $("#abProgText").textContent = `${task}${spent}${warm} · ${c.done}명 완료${c.fail ? ` · 실패 ${c.fail}` : ""}${c.wait + c.running ? ` · 남은 ${c.wait + c.running}명` : ""}${st.running ? "" : c.wait ? " · 멈춤" : " · 끝"}`;
  $("#abSum").textContent = tot ? `${tot}명` : "";
  $("#abStop").hidden = !st.running;
  $("#abResume").hidden = st.running || !c.wait;
  const g = $("#abResults");
  g.innerHTML = st.items.map((it, i) => {
    const im = it.status === "done" ? `<img src="${AB.thumbs[it.id] || ""}">` : it.status === "running" ? `<div class="spin" style="margin:0"></div>` : it.status === "fail" ? esc(it.err || "실패") : "기다리는 중";
    return `<div class="abp ${it.status}${AB.pick.has(it.id) ? " on" : ""}" data-i="${i}">${it.status === "done" ? '<span class="ck"></span>' : ""}
      <div class="im">${im}</div><div class="nm">${esc(it.name)}</div><div class="sb">${esc(it.club || "")}</div>
      <div class="acts">${it.status === "done" ? `<button data-a="big" title="크게 보기 · 지금 사진과 비교">크게</button>` : ""}${it.status !== "running" ? `<button data-a="again" title="다시 그리기">↻ 다시</button>` : ""}<button data-a="drop" title="빼기">✕</button></div></div>`;
  }).join("") || `<div class="empty" style="grid-column:1/-1">비어 있어요.</div>`;
  $$(".abp", g).forEach((el) => {
    const it = st.items[+el.dataset.i];
    el.onclick = (e) => {
      const a = e.target.closest("button")?.dataset.a;
      if (a === "again") { abAgain([it.id]); return; }
      if (a === "drop") { abDrop([it.id]); return; }
      if (a === "big") { openABBig(it); return; }
      if (it.status !== "done") return;
      AB.pick.has(it.id) ? AB.pick.delete(it.id) : AB.pick.add(it.id);
      el.classList.toggle("on"); abQueueBtn();
    };
  });
  abQueueBtn();
}
function abQueueBtn() {
  const n = AB.items.filter((i) => i.status === "done" && AB.pick.has(i.id)).length;
  $("#abQueue").disabled = !n;
  $("#abQueue").textContent = n ? `${n}명 대기열에 넣기` : "고른 것 대기열에 넣기";
}
async function abAgain(ids) {
  const st = await call("batch_again", ids);
  if (st) { ids.forEach((k) => { delete AB.ver[k]; AB.pick.delete(k); }); renderABRun(st); startABPoll(); }
}
async function abDrop(ids) {
  const st = await call("batch_drop", ids);
  if (st) renderABRun(st);
}
async function openABBig(it) {
  AB.big = it;
  const r = await call("batch_big", it.id);
  if (!r || r.error) return;
  $("#abBigName").textContent = r.name;
  $("#abBefore").innerHTML = r.before ? `<img src="${r.before}">` : `<div class="none">사진 없음</div>`;
  $("#abAfter").innerHTML = `<img src="${r.img}">`;
  $("#abPrompt").textContent = r.prompt || "";
  $("#abBig").classList.add("on");
}
$("#abBigX").onclick = () => $("#abBig").classList.remove("on");
$("#abBigAgain").onclick = () => { $("#abBig").classList.remove("on"); if (AB.big) abAgain([AB.big.id]); };
$("#abBigDrop").onclick = () => { $("#abBig").classList.remove("on"); if (AB.big) abDrop([AB.big.id]); };
$("#abStop").onclick = async () => { await call("batch_stop"); toast("지금 그리는 것까지만 하고 멈춰요.", "info", 2500); };
$("#abResume").onclick = async () => { const st = await call("batch_resume"); if (st) { renderABRun(st); startABPoll(); } };
$("#abSelAll").onclick = () => { AB.items.filter((i) => i.status === "done").forEach((i) => AB.pick.add(i.id)); abQueueBtn(); $$("#abResults .abp.done").forEach((e) => e.classList.add("on")); };
$("#abNew").onclick = async () => {
  if (AB.running) { toast("그리는 중이에요. 먼저 멈춰 주세요.", "err"); return; }
  const done = AB.items.filter((i) => i.status === "done").length;
  if (done && !await confirmBox("새로 시작", `대기열에 안 넣은 그림 ${done}장이 지워져요. 새로 시작할까요?`, "지우고 새로", true)) return;
  await call("batch_drop", AB.items.map((i) => i.id));
  showABSetup();
};
$("#abQueue").onclick = async () => {
  const ids = AB.items.filter((i) => i.status === "done" && AB.pick.has(i.id)).map((i) => i.id);
  if (!ids.length) return;
  $("#abQueue").disabled = true;
  const r = await call("batch_to_queue", ids);
  if (!r) return;
  S.queue = r.queue; renderQueue();
  toast(`${r.count}명을 대기열에 넣었어요. 오른쪽 '한 번에 적용'을 누르면 게임에 들어가요.`, "ok", 3500);
  doSearch(true);
  if (!r.items.length) { stopABPoll(); $("#abModal").classList.remove("on"); }   // 다 넣었으면 첫 화면으로
  else renderABRun(r);
};
