/* क्यामेरा अपलोड — फोटो लिन मिल्ने हरेक <input type="file"> को छेउमा "क्यामेराबाट खिच्नुहोस्" बटन.
 *
 * मोबाइल: फोनको क्यामेरा सिधै खुल्छ (capture). कम्प्युटर: वेबक्यामबाट फोटो खिच्ने सानो झ्याल.
 * खिचेको फोटो त्यही फाइल फिल्डमा राखिन्छ — फारम / सर्भर जस्ताको तस्तै (नाम, validation, onchange)।
 * नचाहिने फिल्डमा: data-no-camera। Excel/CSV मात्र लिने (accept मा image नभएका) फिल्डमा आफैँ देखिँदैन।
 */
(function () {
  "use strict";
  var MOBILE = (window.matchMedia && matchMedia("(pointer: coarse)").matches) || /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

  function allowsImage(inp) {
    var a = (inp.getAttribute("accept") || "").toLowerCase();
    return !a || /image|\.jpe?g|\.png|\.webp|\.heic/.test(a);
  }

  function putFile(inp, file) {
    try {
      var dt = new DataTransfer();
      if (inp.multiple) for (var i = 0; i < inp.files.length; i++) dt.items.add(inp.files[i]);
      dt.items.add(file);
      inp.files = dt.files;
    } catch (e) {
      alert("यो ब्राउजरमा क्यामेराको फोटो राख्न सकिएन। फाइल छानेर अपलोड गर्नुहोस्।");
      return;
    }
    inp.dispatchEvent(new Event("input", { bubbles: true }));
    inp.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function phoneCamera(inp) {
    var c = document.createElement("input");
    c.type = "file"; c.accept = "image/*"; c.setAttribute("capture", "environment");
    c.style.display = "none";
    c.addEventListener("change", function () { if (c.files && c.files[0]) putFile(inp, c.files[0]); c.remove(); });
    document.body.appendChild(c);
    c.click();
  }

  // ---------- कम्प्युटर: वेबक्याम झ्याल ----------
  var box, video, shot, stream, target, blob;
  function css(el, s) { el.style.cssText = s; return el; }
  function btn(text, bg, fg) {
    return css(Object.assign(document.createElement("button"), { type: "button", textContent: text }),
      "border:0;border-radius:8px;padding:8px 14px;font:600 13px inherit;cursor:pointer;background:" + bg + ";color:" + fg);
  }
  function build() {
    box = css(document.createElement("div"), "position:fixed;inset:0;z-index:2147483000;background:rgba(15,23,42,.6);display:none;align-items:center;justify-content:center;padding:16px");
    var card = css(document.createElement("div"), "background:#fff;border-radius:14px;max-width:560px;width:100%;padding:14px;box-shadow:0 20px 50px rgba(0,0,0,.3);font-family:inherit");
    var title = css(document.createElement("p"), "margin:0 0 10px;font-weight:700;color:#1e293b;font-size:15px");
    title.textContent = "क्यामेराबाट फोटो खिच्नुहोस्";
    video = css(Object.assign(document.createElement("video"), { autoplay: true, playsInline: true, muted: true }), "width:100%;border-radius:10px;background:#0f172a;max-height:60vh");
    shot = css(document.createElement("img"), "width:100%;border-radius:10px;display:none;max-height:60vh;object-fit:contain;background:#0f172a");
    var msg = css(document.createElement("p"), "margin:8px 0 0;font-size:12px;color:#b91c1c;display:none");
    var bar = css(document.createElement("div"), "display:flex;gap:8px;justify-content:flex-end;margin-top:12px;flex-wrap:wrap");
    var close = btn("रद्द", "#f1f5f9", "#334155"), snap = btn("📷 फोटो खिच्नुहोस्", "#2a47a3", "#fff"),
        retake = btn("फेरि खिच्ने", "#f1f5f9", "#334155"), use = btn("यो फोटो राख्नुहोस्", "#059669", "#fff");
    retake.style.display = use.style.display = "none";
    bar.append(close, retake, snap, use);
    card.append(title, video, shot, msg, bar);
    box.appendChild(card);
    document.body.appendChild(box);
    box.addEventListener("click", function (e) { if (e.target === box) stop(); });
    close.onclick = stop;
    snap.onclick = function () {
      var w = video.videoWidth, h = video.videoHeight;
      if (!w) return;
      var cv = document.createElement("canvas"); cv.width = w; cv.height = h;
      cv.getContext("2d").drawImage(video, 0, 0, w, h);
      cv.toBlob(function (b) {
        blob = b; shot.src = URL.createObjectURL(b);
        shot.style.display = "block"; video.style.display = "none";
        snap.style.display = "none"; retake.style.display = use.style.display = "";
      }, "image/jpeg", 0.9);
    };
    retake.onclick = function () {
      blob = null; shot.style.display = "none"; video.style.display = "block";
      snap.style.display = ""; retake.style.display = use.style.display = "none";
    };
    use.onclick = function () {
      if (!blob) return;
      var d = new Date(), p = function (n) { return String(n).padStart(2, "0"); };
      var name = "camera-" + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "-" + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds()) + ".jpg";
      putFile(target, new File([blob], name, { type: "image/jpeg" }));
      stop();
    };
    box._msg = msg; box._retake = retake;
  }
  function stop() {
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null;
    if (box) { box.style.display = "none"; box._retake.onclick(); }
  }
  function webcam(inp) {
    if (!box) build();
    target = inp; box._msg.style.display = "none"; box._retake.onclick();
    box.style.display = "flex";
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false }).then(function (s) {
      stream = s; video.srcObject = s;
    }).catch(function () {
      box._msg.textContent = "क्यामेरा खुलेन — क्यामेरा जोडिएको छ र ब्राउजरलाई अनुमति दिइएको छ कि हेर्नुहोस्। नभए फाइल छानेर अपलोड गर्नुहोस्।";
      box._msg.style.display = "block";
    });
  }

  function open(inp) {
    if (MOBILE || !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) phoneCamera(inp);
    else webcam(inp);
  }

  // ---------- हरेक फाइल फिल्डमा बटन ----------
  function enhance(root) {
    (root || document).querySelectorAll('input[type="file"]').forEach(function (inp) {
      if (inp.dataset.camReady || inp.hasAttribute("capture") || inp.hasAttribute("data-no-camera") || !allowsImage(inp)) return;
      inp.dataset.camReady = "1";
      var b = document.createElement("button");
      b.type = "button";
      b.className = "cam-upload-btn";
      b.innerHTML = '<i class="fas fa-camera"></i> क्यामेराबाट खिच्नुहोस्';
      css(b, "display:inline-flex;align-items:center;gap:6px;margin-top:6px;padding:5px 10px;border-radius:8px;border:1px solid #bccaee;background:#eef2fb;color:#223a8b;font:600 12px inherit;cursor:pointer");
      b.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); open(inp); });
      // लुकाइएको / पारदर्शी फिल्ड (ड्र्याग-ड्रप label भित्र) भए त्यो label पछि
      var hidden = inp.classList.contains("hidden") || inp.classList.contains("sr-only") || getComputedStyle(inp).opacity === "0";
      var anchor = hidden ? (inp.closest("label") || inp.parentElement) : inp;
      anchor.insertAdjacentElement("afterend", b);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { enhance(document); });
  else enhance(document);
  document.addEventListener("htmx:load", function (e) { enhance(e.detail && e.detail.elt); });
  window.pmsCameraEnhance = enhance;
})();
