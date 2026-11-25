"use strict";
/* FM27 Face Studio — 화면 로직 */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ico = (n, cls = "i") => `<svg class="${cls}"><use href="#i-${n}"/></svg>`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  kind: "player",
  people: { loaded: false, count: 0 },
  results: [],
  selUid: null,
  photo: null,          // {img, w, h, box:[cx,cy,side], auto:[...], nobg, isOriginal}
  queue: [],
  applied: [],
  aSel: new Set(),
  settings: {},
  models: [],
  defaultPrompt: "",
  rembg: false,
  promptDirty: false,
};

/* ------------------------------------------------------------------ API */
let API = null;
function ready() {
  return new Promise((res) => {
    if (window.pywebview && window.pywebview.api) return res(window.pywebview.api);
    window.addEventListener("pywebviewready", () => res(window.pywebview.api));
    // 개발용: 브라우저에서 dev_server.py로 열었을 때
    setTimeout(() => {
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
function busy(on, text = "처리 중…", sub = "") {
  $("#busy").classList.toggle("on", on);
  $("#busyText").textContent = text;
  $("#busySub").textContent = sub;
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

/* ------------------------------------------------------------------ 탭 */
$$(".tab").forEach((b) => b.onclick = () => {
  $$(".tab").forEach((x) => x.classList.toggle("on", x === b));
  $$(".page").forEach((p) => p.classList.toggle("on", p.id === b.dataset.page));
  if (b.dataset.page === "pageApplied") loadApplied();
  else requestAnimationFrame(drawStage);
});

/* ------------------------------------------------------------------ 1. 검색 */
function renderPeopleInfo() {
  const el = $("#peopleInfo");
  if (S.people.loaded) {
    el.innerHTML = `<div class="callout ok">${ico("users")}<div>세이브 인물 <b>${S.people.count.toLocaleString()}</b>명을 불러왔어요.</div></div>`;
  } else {
    el.innerHTML = `<div class="callout">${ico("info")}<div>세이브 인물 목록이 아직 없어요.<br>2단계 플러그인이 완성되면 이름·팀으로 검색할 수 있어요. 지금은 아래에 <b>UID를 직접 입력</b>해 주세요.</div></div>`;
  }
  $("#q").disabled = !S.people.loaded;
  renderResults();
}
function renderResults() {
  const el = $("#results");
  if (!S.people.loaded) { el.innerHTML = ""; return; }
  if (!$("#q").value.trim()) {
    el.innerHTML = `<div class="empty"><div>${ico("search")}<br>이름이나 팀을 입력해 보세요</div></div>`;
    return;
  }
  if (!S.results.length) { el.innerHTML = `<div class="empty"><div>${ico("search")}<br>검색 결과가 없어요</div></div>`; return; }
  el.innerHTML = S.results.map((p, i) => `
    <div class="pcard ${p.uid === S.selUid ? "sel" : ""}" data-i="${i}">
      ${avatar(p)}
      <div class="tx"><div class="nm">${esc(p.name)}</div>
        <div class="sub">${esc(p.club || "무소속")}${p.age ? " · " + esc(p.age) + "세" : ""}${p.nationality ? " · " + esc(p.nationality) : ""}</div></div>
      ${p.newgen ? '<span class="badge ng">뉴젠</span>' : ""}${p.face ? '<span class="badge face">적용됨</span>' : ""}
    </div>`).join("");
  $$(".pcard", el).forEach((c) => c.onclick = () => pickPerson(S.results[+c.dataset.i]));
}
let qTimer;
$("#q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(doSearch, 180); });
async function doSearch() {
  const q = $("#q").value.trim();
  S.results = q ? (await call("search", q, S.kind)) || [] : [];
  renderResults();
}
$$("#kindSeg button").forEach((b) => b.onclick = () => {
  S.kind = b.dataset.kind;
  $$("#kindSeg button").forEach((x) => x.classList.toggle("on", x === b));
  doSearch(); updateCard(); autoPrompt();
});
$("#btnReload").onclick = async () => {
  const r = await call("reload_people");
  if (!r) return;
  S.people = r;
  renderPeopleInfo();
  if (r.status === "missing") toast("세이브 인물 목록 파일이 아직 없어요.");
  else if (r.loaded) { toast(`인물 ${r.count.toLocaleString()}명 불러옴`, "ok"); doSearch(); }
};

function setKind(k) {
  S.kind = k;
  $$("#kindSeg button").forEach((x) => x.classList.toggle("on", x.dataset.kind === k));
}
function person() {
  return {
    uid: $("#fUid").value.trim(), name: $("#fName").value.trim(), club: $("#fClub").value.trim(),
    age: $("#fAge").value.trim(), nationality: $("#fNat").value.trim(), kind: S.kind, newgen: $("#fNewgen").checked,
  };
}
function fillPerson(p) {
  $("#fUid").value = p.uid || ""; $("#fName").value = p.name || ""; $("#fClub").value = p.club || "";
  $("#fAge").value = p.age || ""; $("#fNat").value = p.nationality || ""; $("#fNewgen").checked = !!p.newgen;
  if (p.kind) setKind(p.kind);
  updateCard();
}
function pickPerson(p) {
  S.selUid = p.uid;
  fillPerson(p);
  renderResults();
  S.promptDirty = false;
  autoPrompt();
}
$("#btnClear").onclick = () => { S.selUid = null; fillPerson({}); renderResults(); S.promptDirty = false; autoPrompt(); };
["#fName", "#fClub", "#fAge", "#fNat"].forEach((s) => $(s).addEventListener("input", () => { updateCard(); autoPromptSoon(); }));
$("#fNewgen").onchange = updateCard;
$("#fUid").addEventListener("input", async () => {
  $("#fUid").value = $("#fUid").value.replace(/\D/g, "");
  if (S.selUid && $("#fUid").value !== S.selUid) { S.selUid = null; renderResults(); }
  if (!S.selUid && $("#fUid").value.length >= 10) $("#fNewgen").checked = !!(await call("guess_newgen", $("#fUid").value));
  updateCard();
});
function updateCard() {
  const p = person();
  $("#pvName").textContent = p.name || "이름 없음";
  $("#pvSub").textContent = [p.club || "소속 없음", p.age ? p.age + "세" : "", p.nationality].filter(Boolean).join(" · ");
  $("#pvTags").innerHTML = (p.uid ? `<span class="badge uid">${esc(p.uid)}</span>` : "") +
    (p.newgen ? '<span class="badge ng">뉴젠</span>' : "") +
    `<span class="badge face">${S.kind === "player" ? "선수" : "스태프"}</span>`;
}

/* ------------------------------------------------------------------ 2. 사진 편집기 */
const cv = $("#cv"), ctx = cv.getContext("2d");
const pv = $("#pv"), pctx = pv.getContext("2d");
let view = { s: 1, ox: 0, oy: 0 };

function setPhoto(payload, keepBox = false) {
  return new Promise((res) => {
    const img = new Image();
    img.onload = () => {
      const old = S.photo;
      S.photo = {
        img, w: payload.w, h: payload.h, nobg: payload.nobg, isOriginal: payload.is_original ?? (old ? old.isOriginal : true),
        box: keepBox && old ? old.box : payload.box, auto: payload.box || (old && old.auto),
      };
      $("#drop").style.display = "none";
      ["#btnAuto", "#btnNobg", "#zoom"].forEach((s) => $(s).disabled = false);
      $("#btnRevert").disabled = S.photo.isOriginal;
      $("#btnNobg").classList.toggle("on", !!S.photo.nobg);
      $("#pvBox").classList.toggle("checker", !!S.photo.nobg);
      pv.hidden = false; $("#pvBox .ph0").style.display = "none";
      syncZoom(); drawStage(); res();
      if (!S.promptDirty) autoPrompt();
    };
    img.src = payload.url;
  });
}
function clampBox([cx, cy, side]) {
  const { w, h } = S.photo;
  side = Math.max(16, Math.min(side, Math.max(w, h)));
  cx = side <= w ? Math.min(Math.max(cx, side / 2), w - side / 2) : w / 2;
  cy = side <= h ? Math.min(Math.max(cy, side / 2), h - side / 2) : h / 2;
  return [cx, cy, side];
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
  const pad = 18, s = Math.min((W - pad * 2) / P.w, (H - pad * 2) / P.h);
  view = { s, ox: (W - P.w * s) / 2, oy: (H - P.h * s) / 2 };
  if (P.nobg) { // 투명 표시용 체크무늬
    const c = 10; ctx.save(); ctx.beginPath(); ctx.rect(view.ox, view.oy, P.w * s, P.h * s); ctx.clip();
    for (let y = 0; y < P.h * s; y += c) for (let x = 0; x < P.w * s; x += c) {
      ctx.fillStyle = ((x + y) / c) % 2 ? "#2c3653" : "#3a4566"; ctx.fillRect(view.ox + x, view.oy + y, c, c);
    }
    ctx.restore();
  }
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(P.img, view.ox, view.oy, P.w * s, P.h * s);
  const [cx, cy, side] = P.box;
  const x = view.ox + (cx - side / 2) * s, y = view.oy + (cy - side / 2) * s, d = side * s;
  ctx.save();
  ctx.fillStyle = "rgba(5,8,18,.62)";
  ctx.beginPath(); ctx.rect(0, 0, W, H); ctx.rect(x, y, d, d); ctx.fill("evenodd");
  ctx.strokeStyle = "rgba(255,255,255,.28)"; ctx.lineWidth = 1; ctx.setLineDash([4, 5]);
  for (const k of [1, 2]) {
    ctx.beginPath(); ctx.moveTo(x + d * k / 3, y); ctx.lineTo(x + d * k / 3, y + d); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x, y + d * k / 3); ctx.lineTo(x + d, y + d * k / 3); ctx.stroke();
  }
  ctx.setLineDash([]);
  const g = ctx.createLinearGradient(x, y, x + d, y + d);
  g.addColorStop(0, "#9a85ff"); g.addColorStop(1, "#1fd1a5");
  ctx.strokeStyle = g; ctx.lineWidth = 2.5; ctx.strokeRect(x, y, d, d);
  const L = Math.min(18, d / 5);
  ctx.strokeStyle = "#fff"; ctx.lineWidth = 4; ctx.lineCap = "round";
  for (const [px, py, dx, dy] of [[x, y, 1, 1], [x + d, y, -1, 1], [x, y + d, 1, -1], [x + d, y + d, -1, -1]]) {
    ctx.beginPath(); ctx.moveTo(px + dx * L, py); ctx.lineTo(px, py); ctx.lineTo(px, py + dy * L); ctx.stroke();
  }
  ctx.restore();
  drawPreview();
}
function drawPreview() {
  const P = S.photo; if (!P) return;
  const [cx, cy, side] = P.box, k = P.img.naturalWidth / P.w;
  pctx.clearRect(0, 0, 300, 300);
  pctx.imageSmoothingQuality = "high";
  pctx.drawImage(P.img, (cx - side / 2) * k, (cy - side / 2) * k, side * k, side * k, 0, 0, 300, 300);
}
// 줌 슬라이더: 로그 스케일
function zoomRange() { const P = S.photo; return [Math.log(24), Math.log(Math.max(P.w, P.h))]; }
function syncZoom() {
  if (!S.photo) return;
  const [a, b] = zoomRange(), v = (Math.log(S.photo.box[2]) - a) / (b - a);
  $("#zoom").value = Math.round((1 - v) * 1000);
  $("#zoomTxt").textContent = Math.round(S.photo.box[2] / Math.max(S.photo.w, S.photo.h) * 100) + "%";
}
$("#zoom").addEventListener("input", () => {
  if (!S.photo) return;
  const [a, b] = zoomRange(), v = 1 - $("#zoom").value / 1000;
  const [cx, cy] = S.photo.box;
  S.photo.box = clampBox([cx, cy, Math.exp(a + (b - a) * v)]);
  $("#zoomTxt").textContent = Math.round(S.photo.box[2] / Math.max(S.photo.w, S.photo.h) * 100) + "%";
  drawStage();
});
let drag = null;
cv.addEventListener("mousedown", (e) => { if (S.photo) drag = { x: e.clientX, y: e.clientY, box: [...S.photo.box] }; });
window.addEventListener("mousemove", (e) => {
  if (!drag) return;
  const [cx, cy, side] = drag.box;
  S.photo.box = clampBox([cx + (e.clientX - drag.x) / view.s, cy + (e.clientY - drag.y) / view.s, side]);
  drawStage();
});
window.addEventListener("mouseup", () => drag = null);
cv.addEventListener("wheel", (e) => {
  if (!S.photo) return;
  e.preventDefault();
  const [cx, cy, side] = S.photo.box;
  S.photo.box = clampBox([cx, cy, side * (e.deltaY < 0 ? 0.94 : 1.06)]);
  syncZoom(); drawStage();
}, { passive: false });
cv.addEventListener("dblclick", () => { if (S.photo && S.photo.auto) { S.photo.box = clampBox([...S.photo.auto]); syncZoom(); drawStage(); } });
new ResizeObserver(() => drawStage()).observe($("#stage"));

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
$("#btnAuto").onclick = () => cv.dispatchEvent(new Event("dblclick"));
$("#btnRevert").onclick = async () => { const r = await call("revert_original"); if (r) setPhoto(r); };
$("#btnNobg").onclick = async () => {
  if (!S.photo) return;
  if (!S.rembg) { toast("배경 제거 기능이 아직 설치되지 않았어요.\n프로그램 폴더의 '배경제거_설치.bat'을 실행해 주세요.", "err"); return; }
  const on = !S.photo.nobg;
  busy(true, on ? "배경 지우는 중…" : "되돌리는 중…", on ? "처음 한 번은 모델을 받느라 오래 걸려요" : "");
  const r = await call("set_nobg", on);
  busy(false);
  if (r) setPhoto(r, true);
};

/* ------------------------------------------------------------------ AI */
let pTimer;
function autoPromptSoon() { clearTimeout(pTimer); pTimer = setTimeout(autoPrompt, 300); }
async function autoPrompt(force = false) {
  if (S.promptDirty && !force) return;
  const t = await call("build_prompt", person(), $("#sendPhoto").checked);
  if (typeof t === "string") { $("#prompt").value = t; if (force) S.promptDirty = false; }
}
$("#prompt").addEventListener("input", () => S.promptDirty = true);
$("#btnPrompt").onclick = () => autoPrompt(true);
$("#sendPhoto").onchange = async () => {
  S.settings.send_photo = $("#sendPhoto").checked;
  call("save_settings", S.settings);
  if (!S.promptDirty) autoPrompt();
};
$("#btnAI").onclick = async () => {
  let prompt = $("#prompt").value.trim();
  if (!prompt) { await autoPrompt(true); prompt = $("#prompt").value.trim(); }
  const send = $("#sendPhoto").checked && !!S.photo;
  busy(true, "AI가 사진을 만드는 중…", S.settings.gemini_model + " · 보통 10~40초");
  $("#btnAI").disabled = true;
  const r = await call("ai_generate", prompt, send);
  busy(false); $("#btnAI").disabled = false;
  if (!r) return;
  if (r.error === "need_key") { toast("설정에서 제미나이 API 키를 먼저 입력해 주세요.", "err"); openSettings(); $("#sKey").focus(); return; }
  await setPhoto(r);
  toast("AI 사진 완성! 자르기 위치를 확인하고 대기열에 추가하세요.", "ok");
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
        <div style="display:flex;gap:4px;margin-top:3px"><span class="badge uid">${esc(q.uid)}</span>${q.newgen ? '<span class="badge ng">뉴젠</span>' : ""}${q.kind === "staff" ? '<span class="badge face">스태프</span>' : ""}</div></div>
      <button class="x" data-id="${q.id}" title="빼기">${ico("x")}</button></div>`).join("");
  $$(".x", el).forEach((b) => b.onclick = async () => { const r = await call("queue_remove", [b.dataset.id]); if (r) { S.queue = r.queue; renderQueue(); } });
}
$("#btnAdd").onclick = async () => {
  const p = person();
  if (!/^\d+$/.test(p.uid)) { toast("UID(숫자)를 입력하거나 검색 결과에서 인물을 골라 주세요.", "err"); $("#fUid").focus(); return; }
  if (!S.photo) { toast("먼저 사진을 넣거나 AI로 만들어 주세요.", "err"); return; }
  let r = await call("add_to_queue", p, S.photo.box, false);
  if (r && r.confirm === "duplicate") {
    if (!await confirmBox("이미 대기열에 있어요", `UID ${p.uid}가 대기열에 있어요.\n새 사진으로 바꿀까요?`, "바꾸기")) return;
    r = await call("add_to_queue", p, S.photo.box, true);
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
    toast(`${r.count}명 적용 완료!\nFM27을 완전히 종료한 뒤 다시 켜면 반영돼요.`, "ok", 6000);
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
function openSettings() {
  const s = S.settings;
  $("#sG").value = s.graphics_dir || ""; $("#sP").value = s.people_file || ""; $("#sSize").value = s.output_size || 250;
  $("#sKey").value = s.gemini_key || ""; $("#sModel").value = s.gemini_model || ""; $("#sTpl").value = s.prompt_template || "";
  $("#models").innerHTML = S.models.map((m) => `<option value="${esc(m)}">`).join("");
  $("#mSettings").classList.add("on");
}
$("#btnSettings").onclick = openSettings;
$$("[data-close]").forEach((b) => b.onclick = () => b.closest(".modal").classList.remove("on"));
$("#btnShowKey").onclick = () => { const k = $("#sKey"); k.type = k.type === "password" ? "text" : "password"; };
$("#lnkStudio").onclick = () => call("open_url", "https://aistudio.google.com/apikey");
$("#lnkDefault").onclick = () => $("#sTpl").value = S.defaultPrompt;
$$("[data-pick]").forEach((b) => b.onclick = async () => {
  const r = b.dataset.pick === "folder" ? await call("pick_folder", $("#sG").value) : await call("pick_file", "json");
  if (r) (b.dataset.pick === "folder" ? $("#sG") : $("#sP")).value = r;
});
$("#btnSaveSettings").onclick = async () => {
  const r = await call("save_settings", {
    graphics_dir: $("#sG").value, people_file: $("#sP").value, output_size: +$("#sSize").value || 250,
    gemini_key: $("#sKey").value, gemini_model: $("#sModel").value, prompt_template: $("#sTpl").value,
    send_photo: $("#sendPhoto").checked,
  });
  if (!r) return;
  applyState(r);
  $("#mSettings").classList.remove("on");
  toast("설정을 저장했어요.", "ok", 2000);
  if (!S.promptDirty) autoPrompt();
};
$("#btnFolder").onclick = () => call("open_pack_dir");
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $$(".modal.on").forEach((m) => m.classList.remove("on")); });

/* ------------------------------------------------------------------ 시작 */
function applyState(st) {
  S.settings = st.settings; S.models = st.models; S.defaultPrompt = st.default_prompt; S.rembg = st.rembg;
  S.people = st.people; S.queue = st.queue;
  $("#aiModel").textContent = st.settings.gemini_model;
  $("#sendPhoto").checked = !!st.settings.send_photo;
  if (!S.rembg) $("#btnNobg").title = "'배경제거_설치.bat' 실행 후 사용 가능";
  renderPeopleInfo(); renderQueue();
}
(async () => {
  API = await ready();
  const st = await call("get_state");
  const boot = $("#boot");
  boot.classList.add("done"); setTimeout(() => boot.remove(), 400);
  if (!st) return;
  applyState(st);
  updateCard();
  autoPrompt();
  refreshAppliedCount();
})();
