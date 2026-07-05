// ==UserScript==
// @name         RealEstork FB Group Capture
// @namespace    realestork
// @version      1.1.3
// @description  Passive capture post chính chủ từ group Facebook đóng → POST về bot localhost. Đọc THỤ ĐỘNG màn hình FB của 1 account thật (profile riêng), tự cuộn + xoay vòng group. KHÔNG tự đăng nhập, KHÔNG bơm traffic lạ.
// @author       RealEstork
// @match        https://www.facebook.com/groups/*
// @run-at       document-idle
// @noframes
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

/*
 ─────────────────────────────────────────────────────────────────────────────
 CÀI ĐẶT (1 lần, trên Chrome profile RIÊNG "RealEstork Bot"):
   1. Cài extension Tampermonkey.
   2. Tampermonkey → Create new script → dán toàn bộ file này → Save (Ctrl+S).
   3. Sửa khối CONFIG bên dưới:
        - token: khớp ingest_token trong config/spiders.yaml (hoặc FB_INGEST_TOKEN trong .env)
        - groups: dán URL 9 group đóng của anh.
   4. Login via FB trong profile này; đảm bảo via đã là member 9 group.
   5. Bật bot (enabled: true cho facebook_groups + restart) → mở 1 group → script tự chạy.

 CƠ CHẾ: script chạy trên mọi trang /groups/* → tự cuộn chậm, đọc post hiện trên
 màn hình, POST post mới về receiver localhost, rồi sau dwellMs tự navigate sang
 group kế tiếp (xoay vòng). Chống trùng tại chỗ bằng localStorage (seen post-id).

 GIỚI HẠN (đã biết): chỉ bắt text HIỆN ra; KHÔNG tự bấm "Xem thêm" (giữ passive,
 né anti-bot) → post quá dài có thể bị cụt đuôi. Post cho thuê thường ngắn nên OK.
 ─────────────────────────────────────────────────────────────────────────────
*/

(function () {
  'use strict';

  // ======================= CONFIG — SỬA Ở ĐÂY =======================
  const CONFIG = {
    receiver: 'http://127.0.0.1:8787/ingest',  // khớp ingest_host:ingest_port
    token: 'demo123',          // khớp ingest_token / FB_INGEST_TOKEN
    groups: [
      'https://www.facebook.com/groups/239359157957166',
      'https://www.facebook.com/groups/412641129723985',
      'https://www.facebook.com/groups/1003269067182777',
      'https://www.facebook.com/groups/139389175910565',
      'https://www.facebook.com/groups/199211687471437',
      'https://www.facebook.com/groups/1023739918044976',
      'https://www.facebook.com/groups/298471333059025',
      'https://www.facebook.com/groups/126669044746335',
    ],
    rotate: true,                  // tự xoay vòng group; false = chỉ capture group đang mở
    dwellMs: [90000, 150000],      // ở mỗi group 90–150s (random) rồi sang group kế
    captureEveryMs: 6000,          // quét DOM + cuộn mỗi 6s
    scrollPx: [500, 1200],         // cuộn ngẫu nhiên 500–1200px mỗi nhịp
    postBatch: 25,                 // gửi tối đa N post/lần POST
    maxSeen: 6000,                 // cap localStorage seen set
    badge: true,                   // hiện badge trạng thái góc màn hình
    sortParam: 'sorting_setting=CHRONOLOGICAL',  // ép group sort "Bài viết mới" (chronological) cho scan-until-seen. '' = tắt.
    scanUntilSeen: true,           // xoay group SỚM khi đã cuộn tới vùng post đã gửi (thay vì đợi hết dwell)
    scanSeenTicks: 3,              // số tick liên tiếp KHÔNG có post mới thì coi là "đã quét sạch"
    minDwellMs: 20000,             // tối thiểu ở group 20s trước khi cho phép xoay sớm (chờ feed load)
  };
  // ==================================================================

  // Bỏ group placeholder chưa điền; nếu rỗng → tắt rotate (vẫn capture group đang mở).
  CONFIG.groups = (CONFIG.groups || []).filter((u) => u && !/REPLACE_GROUP/.test(u));
  if (CONFIG.groups.length === 0) CONFIG.rotate = false;

  const LS_SEEN = 'realestork_seen_ids';
  const LS_IDX = 'realestork_rotate_idx';
  const rnd = (a, b) => Math.floor(a + Math.random() * (b - a));

  // ---- seen set (chống re-POST cùng post) ----
  function loadSeen() {
    try { return new Set(JSON.parse(localStorage.getItem(LS_SEEN) || '[]')); }
    catch (e) { return new Set(); }
  }
  // localStorage.setItem ném QuotaExceededError khi origin facebook.com đầy storage
  // (FB xài gần hết quota). Nếu ném ngay TRƯỚC lệnh điều hướng → rotation chết (đây
  // CHÍNH là bug "kẹt không nhảy"). safeSet: thử set; đầy thì dọn bớt seen set của
  // MÌNH để nhường chỗ rồi thử lại; vẫn đầy thì bỏ qua — TUYỆT ĐỐI không ném.
  function safeSet(key, val) {
    try { localStorage.setItem(key, val); return true; }
    catch (e) {
      try {
        const arr = JSON.parse(localStorage.getItem(LS_SEEN) || '[]');
        if (arr.length > 500) localStorage.setItem(LS_SEEN, JSON.stringify(arr.slice(-500)));
        else localStorage.removeItem(LS_SEEN);
        localStorage.setItem(key, val);
        return true;
      } catch (e2) {
        console.log('[RealEstork] localStorage đầy — bỏ qua set ' + key + ' (' + (e2 && e2.name) + ')');
        return false;
      }
    }
  }
  function saveSeen(set) {
    let arr = [...set];
    if (arr.length > CONFIG.maxSeen) arr = arr.slice(arr.length - CONFIG.maxSeen);
    safeSet(LS_SEEN, JSON.stringify(arr));
  }
  const seen = loadSeen();
  const inflight = new Set();   // post đang chờ POST 200 — tránh gửi trùng trong lúc chờ

  // ---- helpers ----
  function currentGroupId() {
    const m = location.pathname.match(/\/groups\/([^/]+)/);
    return m ? m[1] : null;
  }
  function groupName() {
    const h1 = document.querySelector('h1');
    if (h1 && h1.textContent.trim()) return h1.textContent.trim();
    return (document.title || '').replace(/\s*\|\s*Facebook.*$/, '').trim();
  }
  function abs(href) {
    if (!href) return '';
    return href.startsWith('http') ? href : 'https://www.facebook.com' + href;
  }
  // Gắn param sort "Bài viết mới" vào URL group (nếu bật) → newest-first cho scan-until-seen.
  function withSort(url) {
    if (!CONFIG.sortParam) return url;
    const base = url.split('#')[0];
    return base + (base.includes('?') ? '&' : '?') + CONFIG.sortParam;
  }

  // relative time (VN + EN) → epoch seconds, hoặc null nếu không parse được
  function parseRelTime(t) {
    if (!t) return null;
    t = t.toLowerCase().trim();
    const now = Math.floor(Date.now() / 1000);
    if (/vừa xong|just now|vài giây|^now$/.test(t)) return now;
    let m;
    if ((m = t.match(/(\d+)\s*(phút|phut|min|m)\b/))) return now - (+m[1]) * 60;
    if ((m = t.match(/(\d+)\s*(giờ|gio|hour|hrs?|h)\b/))) return now - (+m[1]) * 3600;
    if ((m = t.match(/(\d+)\s*(ngày|ngay|days?|d)\b/))) return now - (+m[1]) * 86400;
    if ((m = t.match(/(\d+)\s*(tuần|tuan|weeks?|w)\b/))) return now - (+m[1]) * 604800;
    if (/hôm qua|yesterday/.test(t)) return now - 86400;
    return null;
  }

  // ---- hash nội dung → id ổn định (FB không cho permalink sạch nữa) ----
  function hashStr(s) {
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
    return h.toString(36);
  }

  // ---- capture post từ feed ----
  // DOM FB 2026: post = div[role="feed"] > div (KHÔNG còn div[role="article"]).
  // Trả CANDIDATE: dedupKey ổn định (hash uid+text, không phụ thuộc link) +
  // realId/realPermalink (nếu FB đã lộ) + base data. Việc quyết định gửi ngay
  // (có link thật) hay chờ ảnh render là do tick() xử lý.
  function capturePosts() {
    const out = [];
    const gid = currentGroupId();
    const gname = groupName();
    const feedDivs = document.querySelectorAll('div[role="feed"] > div');

    feedDivs.forEach((post) => {
      // post thật = có link tới /user/ (tác giả). Loại header "sort by", ô trống.
      const userA = post.querySelector('a[href*="/user/"]');
      if (!userA) return;
      const uid = (userA.getAttribute('href').match(/\/user\/(\d+)/) || [])[1] || '';

      const story = post.querySelector(
        '[data-ad-rendering-role="story_message"], [data-ad-comet-preview="message"], [data-ad-preview="message"]'
      );

      // ── Expand "Xem thêm"/"See more" để lấy FULL text (SĐT + thông số thường ở
      // cuối bài, rơi vào phần bị FB cắt). Click synthetic — expand text KHÔNG bị
      // FB gate như reveal permalink nên thường chạy. Match ĐÚNG "xem thêm"/"see
      // more" (bỏ "Thu gọn"/"See less" và "Xem thêm N bình luận").
      let seeMore = false;
      (story || post).querySelectorAll('[role="button"]').forEach((b) => {
        const lb = (b.innerText || '').trim().toLowerCase().replace(/^[^0-9a-zà-ỹ]+/i, '');
        if (lb === 'xem thêm' || lb === 'see more') { try { b.click(); } catch (e) {} seeMore = true; }
      });

      // text: story_message chuẩn nhất, fallback khối dir=auto dài nhất
      let text = '';
      if (story) text = story.innerText.trim();
      if (!text) {
        let best = '';
        post.querySelectorAll('div[dir="auto"]').forEach((d) => {
          const t = d.innerText.trim();
          if (t.length > best.length) best = t;
        });
        text = best;
      }
      // cap 8000 ký tự (an toàn — full text post thực tế hiếm khi vượt)
      text = text.replace(/\s*[….]*\s*(See more|Xem thêm|See less|Thu g[ọo]n)\s*$/i, '').trim().slice(0, 8000);
      if (text.length < 10) return; // post chỉ ảnh / chưa render → bỏ
      // text-ready khi KHÔNG còn nút "Xem thêm" chưa mở (vừa click tick này → chờ tick sau expand xong)
      const textReady = !seeMore;

      // dedupKey ổn định (KHÔNG phụ thuộc link) → dùng cho seen/inflight/pending.
      const dedupKey = 'fbh_' + hashStr(uid + '|' + text.slice(0, 120));
      if (seen.has(dedupKey) || inflight.has(dedupKey)) return;

      // Link BÀI CHI TIẾT (nếu FB đã lộ). Post-id lấy được từ link ảnh qua set=gm
      // HOẶC set=pcb — CẢ HAI đều là group post id → /posts/<id>/ mở đúng bài gốc.
      // (Xác nhận thực tế: pcb id mở ra nguyên bài, không phải album.)
      let realId = '', realPermalink = '';
      for (const a of post.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        let mm;
        if ((mm = href.match(/\/(?:posts|permalink)\/(pfbid[A-Za-z0-9]+|\d+)/)) ||
            (mm = href.match(/[?&](?:multi_permalinks|story_fbid)=(pfbid[A-Za-z0-9]+|\d+)/)) ||
            (mm = href.match(/[?&]set=(?:gm|pcb)\.(\d+)/))) {
          realId = mm[1];
          realPermalink = 'https://www.facebook.com/groups/' + gid + '/posts/' + mm[1] + '/';
          break;
        }
        if ((mm = href.match(/\/commerce\/listing\/(\d+)/))) {
          realId = mm[1];
          realPermalink = 'https://www.facebook.com/commerce/listing/' + mm[1] + '/';
          break;
        }
      }

      // author name (best-effort): aria-label / heading
      let authorName = userA.getAttribute('aria-label') || userA.innerText.trim();
      if (!authorName) {
        const h = post.querySelector('h2, h3, h4, [role="heading"], strong');
        if (h) authorName = h.innerText.trim().split('\n')[0].slice(0, 60);
      }

      // timestamp (best-effort): anchor có text dạng "20m" / "5 giờ"
      let createdTime = null;
      for (const a of post.querySelectorAll('a[href]')) {
        const t = (a.innerText || '').trim();
        if (t.length <= 12 && (
            /^\d+\s*(phút|gi[ờo]|ng[àa]y|tu[ầa]n|h|d|m|w|min|hr)\b/i.test(t) ||
            /vừa xong|just now|hôm qua|yesterday/i.test(t))) {
          const ct = parseRelTime(t);
          if (ct) { createdTime = ct; break; }
        }
      }

      // ảnh (best-effort): chỉ ảnh nội dung từ CDN
      const images = [];
      post.querySelectorAll('img[src]').forEach((im) => {
        const src = im.getAttribute('src');
        if (src && /fbcdn|scontent/.test(src) && images.length < 10) images.push(src);
      });

      out.push({
        dedupKey: dedupKey,
        uid: uid,
        realId: realId,
        realPermalink: realPermalink,
        textReady: textReady,
        base: {
          group_id: gid,
          group_name: gname,
          author_name: authorName || '',
          author_id: uid || null,
          author_url: uid ? ('https://www.facebook.com/groups/' + gid + '/user/' + uid + '/') : '',
          text: text,
          created_time: createdTime,
          images: images,
        },
      });
    });

    return out;
  }

  // Dựng payload gửi bot. useReal=true → link bài chi tiết; false → fallback link người đăng.
  function buildPayload(cand, useReal) {
    const gid = cand.base.group_id;
    let post_id, permalink;
    if (useReal && cand.realId) {
      post_id = cand.realId;
      permalink = cand.realPermalink;
    } else {
      post_id = cand.dedupKey;
      permalink = cand.uid
        ? ('https://www.facebook.com/groups/' + gid + '/user/' + cand.uid + '/')
        : ('https://www.facebook.com/groups/' + gid);
    }
    return Object.assign({ post_id: post_id, permalink: permalink }, cand.base);
  }

  // ---- POST về receiver ----
  // items: [{payload, key}]. Key (dedupKey) chỉ vào `seen` SAU khi POST 200 →
  // receiver off / lỗi mạng thì post được giữ lại để thử lại (không bị "nuốt").
  function sendItems(items) {
    if (!items.length) return;
    const posts = items.map((it) => it.payload);
    const keys = items.map((it) => it.key);
    keys.forEach((k) => inflight.add(k));
    GM_xmlhttpRequest({
      method: 'POST',
      url: CONFIG.receiver,
      headers: { 'Content-Type': 'application/json', 'X-Ingest-Token': CONFIG.token },
      data: JSON.stringify({ posts }),
      timeout: 8000,
      onload: (res) => {
        if (res.status === 200) {
          keys.forEach((k) => { seen.add(k); inflight.delete(k); });
          saveSeen(seen);
          captured += keys.length;
          log('POST 200 — gửi ' + keys.length + ' post (tổng ' + captured + ')');
        } else {
          keys.forEach((k) => inflight.delete(k));
          log('POST ' + res.status + ' (token sai? ' + (res.responseText || '').slice(0, 60) + ') — sẽ thử lại');
        }
      },
      onerror: () => { keys.forEach((k) => inflight.delete(k)); log('POST lỗi — receiver chạy chưa? sẽ thử lại'); },
      ontimeout: () => { keys.forEach((k) => inflight.delete(k)); log('POST timeout — sẽ thử lại'); },
    });
  }

  // ---- badge + log ----
  let captured = 0;
  let badgeEl = null;
  function setupBadge() {
    if (!CONFIG.badge) return;
    try {
      badgeEl = document.createElement('div');
      badgeEl.id = 'realestork-badge';
      (document.body || document.documentElement).appendChild(badgeEl);
      GM_addStyle('#realestork-badge{position:fixed;z-index:2147483647;bottom:12px;right:12px;background:#1b5e20;color:#fff;font:12px/1.4 sans-serif;padding:6px 10px;border-radius:8px;opacity:.88;max-width:260px;pointer-events:none}');
    } catch (e) {}
  }
  function badge(msg) { if (badgeEl) badgeEl.textContent = 'RealEstork — ' + msg; }
  function log(msg) { console.log('[RealEstork]', msg); badge(msg); }

  // ---- rotation index: đồng bộ với group đang mở ----
  let idx = parseInt(localStorage.getItem(LS_IDX) || '0', 10) || 0;
  if (CONFIG.rotate) {
    const here = location.href.split('?')[0].replace(/\/$/, '');
    const found = CONFIG.groups.findIndex((g) => here.startsWith(g.replace(/\/$/, '')));
    if (found >= 0) idx = found;
  }
  // Điều hướng CỨNG. `location.href=` TRONG sandbox Tampermonkey là NO-OP (đã xác
  // minh: gõ tay cùng URL trong Console/page-context thì trang nhảy, nhưng script
  // gán thì đứng im). => ưu tiên unsafeWindow.location (window THẬT của trang, đúng
  // ngữ cảnh Console). Fallback nhiều lớp + log lỗi để không câm lặng.
  function hardNav(url) {
    try {
      if (typeof unsafeWindow !== 'undefined' && unsafeWindow && unsafeWindow.location) {
        unsafeWindow.location.href = url;
        return;
      }
    } catch (e) { console.log('[RealEstork] unsafeWindow nav lỗi:', e); }
    try { window.location.assign(url); return; } catch (e) { console.log('[RealEstork] assign lỗi:', e); }
    try { location.href = url; } catch (e) { console.log('[RealEstork] href lỗi:', e); }
  }

  // URL group kế + CHỐNG navigation no-op: nếu target trùng URL hiện tại (vd list
  // chỉ còn 1 group, hoặc FB canonical hoá về đúng URL đang đứng) thì gán
  // location.href sẽ KHÔNG nạp lại trang → kẹt. Thêm cache-buster ép reload thật.
  function buildRotateTarget(nextIdx) {
    let target = withSort(CONFIG.groups[nextIdx]);
    if (target.split('#')[0] === location.href.split('#')[0]) {
      target += (target.includes('?') ? '&' : '?') + '_rt=' + Date.now();
    }
    return target;
  }
  function rotateNext() {
    if (!CONFIG.rotate || CONFIG.groups.length === 0) return;
    idx = (idx + 1) % CONFIG.groups.length;
    safeSet(LS_IDX, String(idx));
    log('chuyển sang group ' + (idx + 1) + '/' + CONFIG.groups.length);
    const target = buildRotateTarget(idx);
    setTimeout(() => { hardNav(target); }, 1500);
  }

  // ---- main tick (có cơ chế CHỜ ẢNH RENDER để moi permalink chi tiết) ----
  const pending = new Map();   // dedupKey → { count, cand }: post đã thấy nhưng chưa có link thật
  const MAX_WAIT_TICKS = 3;    // chờ tối đa ~3 nhịp (~18s) cho ảnh render rồi mới chịu fallback
  let rotateAt = 0;            // mốc (ms) sẽ chuyển group — dùng cho badge đếm ngược
  let capTimer = null, dwellTimer = null;  // timer refs — cần clear được khi xoay sớm
  let rotating = false;        // guard tránh xoay 2 lần (dwell-cap + scan-until-seen cùng lúc)
  let emptyStreak = 0;         // số tick liên tiếp KHÔNG có post mới (tín hiệu scan-until-seen)
  let groupEnteredAt = Date.now();  // mốc vào group hiện tại (cho minDwell)

  // Gửi hết pending best-effort trước khi rời group (tránh mất post đang chờ permalink).
  function flushPending() {
    const toSend = [];
    for (const [key, v] of pending) toSend.push({ payload: buildPayload(v.cand, !!v.cand.realId), key: key });
    pending.clear();
    if (toSend.length) sendItems(toSend);
  }
  // Xoay group — từ dwell-cap HOẶC scan-until-seen. Clear timer + flush pending trước.
  function doRotate(reason) {
    if (rotating) return;
    rotating = true;
    if (capTimer) clearInterval(capTimer);
    if (dwellTimer) clearTimeout(dwellTimer);
    if (reason) log(reason);
    flushPending();
    rotateNext();
  }

  function tick() {
    if (!currentGroupId()) { badge('không phải trang group — chờ'); return; }
    window.scrollBy(0, rnd(CONFIG.scrollPx[0], CONFIG.scrollPx[1]));

    const feedN = document.querySelectorAll('div[role="feed"] > div').length;
    const cands = capturePosts();

    // già hoá mọi pending hiện có (mỗi nhịp +1)
    for (const v of pending.values()) v.count++;

    const toSend = [];
    for (const c of cands) {
      if (c.realId && c.textReady) {
        toSend.push({ payload: buildPayload(c, true), key: c.dedupKey });  // đủ link + text full → gửi ngay
        pending.delete(c.dedupKey);
      } else if (pending.has(c.dedupKey)) {
        const p = pending.get(c.dedupKey);
        // giữ bản có text DÀI HƠN (sau khi "Xem thêm" expand xong, text mới đầy đủ)
        if ((c.base.text || '').length >= (p.cand.base.text || '').length) p.cand = c;
      } else {
        pending.set(c.dedupKey, { count: 1, cand: c });   // chưa đủ (thiếu link HOẶC text chưa expand) → chờ
      }
    }
    // pending chờ đủ lâu → gửi best-effort: link thật nếu đã có, kèm text dài nhất gom được
    for (const [key, v] of pending) {
      if (v.count >= MAX_WAIT_TICKS) {
        toSend.push({ payload: buildPayload(v.cand, !!v.cand.realId), key: key });
        pending.delete(key);
      }
    }

    if (toSend.length) sendItems(toSend);

    // ── SCAN-UNTIL-SEEN: capturePosts đã lọc bỏ post seen/inflight → cands rỗng
    // nghĩa là đã cuộn tới vùng toàn post đã gửi (không còn tin mới). Đủ N tick
    // liên tiếp + đã ở group tối thiểu minDwell → xoay sớm (khỏi phí thời gian).
    if (cands.length === 0 && feedN > 3) emptyStreak++;
    else emptyStreak = 0;
    if (CONFIG.rotate && CONFIG.scanUntilSeen && !rotating &&
        emptyStreak >= CONFIG.scanSeenTicks &&
        (Date.now() - groupEnteredAt) >= CONFIG.minDwellMs) {
      doRotate('hết tin mới (scan-until-seen) → xoay sớm');
      return;
    }

    const pos = CONFIG.rotate ? ((idx % CONFIG.groups.length) + 1) + '/' + CONFIG.groups.length : 'manual';
    const left = rotateAt ? ' · tối đa ' + Math.max(0, Math.round((rotateAt - Date.now()) / 1000)) + 's' : '';
    badge('g' + pos + ' · feed ' + feedN + ' · chờ ' + pending.size + ' · sent ' + captured +
          (emptyStreak ? ' · hết tin ' + emptyStreak + '/' + CONFIG.scanSeenTicks + ' → xoay' : '') + left);
    console.log('[RealEstork] tick: feed=' + feedN + ' cands=' + cands.length +
                ' pending=' + pending.size + ' sent=' + captured);
  }

  // ---- start ----
  // Ép sort "Bài viết mới" 1 lần nếu URL group chưa có param (loop-safe: sau redirect
  // URL đã có key → không lặp). Chỉ khi bật rotate + sortParam.
  if (CONFIG.rotate && CONFIG.sortParam) {
    const sortKey = CONFIG.sortParam.split('=')[0];
    if (sortKey && currentGroupId() && !location.search.includes(sortKey + '=')) {
      hardNav(location.href.split('?')[0].split('#')[0] + '?' + CONFIG.sortParam);
      return;
    }
  }
  setupBadge();
  log('khởi động' + (CONFIG.rotate ? '' : ' (rotate OFF — điền groups để bật xoay vòng)'));
  groupEnteredAt = Date.now();
  capTimer = setInterval(tick, CONFIG.captureEveryMs);
  setTimeout(tick, 2500); // chờ feed render

  if (CONFIG.rotate) {
    const dwell = rnd(CONFIG.dwellMs[0], CONFIG.dwellMs[1]);
    rotateAt = Date.now() + dwell;
    dwellTimer = setTimeout(() => doRotate('hết thời gian ở group → xoay'), dwell);

    // ── WATCHDOG (độc lập, doRotate KHÔNG xoá) ──────────────────────────────
    // Toàn bộ vòng xoay dựa trên "reload → script chạy lại → set timer mới". Nếu
    // reload không trọn vẹn (FB nuốt navigation, script chết lúc load, tab hidden
    // không render, hoặc doRotate đã clear timer + kẹt rotating=true), mọi timer
    // biến mất và script đứng im vô hạn. Watchdog là interval RIÊNG: cứ 15s kiểm
    // "ở group này bao lâu rồi", quá trần cứng thì ÉP nhảy group bất kể trạng thái
    // nội bộ. Trần > dwell max để không cắt nhầm group đang chạy lành mạnh.
    const HARD_CAP_MS = Math.max(CONFIG.dwellMs[1] + 60000, 180000);
    let watchdogFired = false;
    setInterval(() => {
      if (watchdogFired) return;
      const elapsed = Date.now() - groupEnteredAt;
      if (elapsed <= HARD_CAP_MS) return;
      watchdogFired = true;
      log('WATCHDOG: kẹt ' + Math.round(elapsed / 1000) + 's → ép nhảy group');
      rotating = false;                        // thoát deadlock
      if (capTimer) clearInterval(capTimer);
      if (dwellTimer) clearTimeout(dwellTimer);
      idx = (idx + 1) % CONFIG.groups.length;  // ép sang group kế
      safeSet(LS_IDX, String(idx));            // safeSet: quota đầy cũng KHÔNG ném chặn nav
      hardNav(buildRotateTarget(idx));         // unsafeWindow + chống no-op → luôn nạp lại
    }, 15000);
  }
})();
