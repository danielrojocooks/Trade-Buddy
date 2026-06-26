// Two photos -> downscale -> one /check call -> emoji verdict.

const els = {
  capture: document.getElementById("capture"),
  loading: document.getElementById("loading"),
  result: document.getElementById("result"),
  redTile: document.getElementById("redTile"),
  yellowTile: document.getElementById("yellowTile"),
  redInput: document.getElementById("redInput"),
  yellowInput: document.getElementById("yellowInput"),
  redThumb: document.getElementById("redThumb"),
  yellowThumb: document.getElementById("yellowThumb"),
  goBtn: document.getElementById("goBtn"),
  againBtn: document.getElementById("againBtn"),
  face: document.getElementById("face"),
  headline: document.getElementById("headline"),
  gem: document.getElementById("gem"),
  gemNote: document.getElementById("gemNote"),
  cards: document.getElementById("cards"),
  redList: document.getElementById("redList"),
  yellowList: document.getElementById("yellowList"),
};

const photos = { red: null, yellow: null }; // base64 (no prefix)

// Resize to max 1024px on the long edge and return base64 JPEG (smaller upload,
// fewer image tokens, plenty of detail for card ID).
function processFile(file) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const max = 1024;
      let { width, height } = img;
      if (width > height && width > max) { height = height * max / width; width = max; }
      else if (height > max) { width = width * max / height; height = max; }
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d").drawImage(img, 0, 0, width, height);
      const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
      resolve({ base64: dataUrl.split(",")[1], dataUrl });
    };
    img.src = URL.createObjectURL(file);
  });
}

function wireTile(side, tile, input, thumb) {
  tile.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    if (!input.files || !input.files[0]) return;
    const { base64, dataUrl } = await processFile(input.files[0]);
    photos[side] = base64;
    thumb.src = dataUrl;
    thumb.hidden = false;
    tile.classList.add("done");
    els.goBtn.disabled = !(photos.red && photos.yellow);
  });
}

wireTile("red", els.redTile, els.redInput, els.redThumb);
wireTile("yellow", els.yellowTile, els.yellowInput, els.yellowThumb);

function show(view) {
  els.capture.hidden = view !== "capture";
  els.loading.hidden = view !== "loading";
  els.result.hidden = view !== "result";
}

function renderList(ul, cards) {
  ul.innerHTML = "";
  for (const c of cards || []) {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "dot t-" + c.tier;
    li.appendChild(dot);
    li.appendChild(document.createTextNode(c.name));
    ul.appendChild(li);
  }
}

els.goBtn.addEventListener("click", async () => {
  show("loading");
  try {
    const res = await fetch("/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        red_image: photos.red,
        yellow_image: photos.yellow,
        red_media_type: "image/jpeg",
        yellow_media_type: "image/jpeg",
      }),
    });
    if (!res.ok) throw new Error("bad response");
    const data = await res.json();

    els.face.src = "/faces/" + data.face + ".png";
    els.headline.textContent = data.headline || "All done!";
    if (data.gem_alert) {
      els.gemNote.textContent = data.gem_note || "One of these might be worth real money! Show a grown-up.";
      els.gem.hidden = false;
    } else {
      els.gem.hidden = true;
    }
    els.cards.hidden = data.cards_found === false;
    renderList(els.redList, data.red_cards);
    renderList(els.yellowList, data.yellow_cards);
    show("result");
  } catch (e) {
    els.face.src = "/faces/error.png";
    els.headline.textContent = "Something happened. Please try again.";
    els.gem.hidden = true;
    els.cards.hidden = true;
    show("result");
  }
});

els.againBtn.addEventListener("click", () => {
  photos.red = photos.yellow = null;
  els.redInput.value = els.yellowInput.value = "";
  els.redThumb.hidden = els.yellowThumb.hidden = true;
  els.redTile.classList.remove("done");
  els.yellowTile.classList.remove("done");
  els.goBtn.disabled = true;
  show("capture");
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
