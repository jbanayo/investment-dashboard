/* First-run tour: coachmarks that walk through the app in the order it's used.
 *
 * Steps are tied to a page path and a [data-tour] anchor. Moving to a step on
 * another page navigates there with ?tour=<index>, so the tour survives page
 * loads without browser storage. Leaving the tour's path simply ends it.
 */
(() => {
  const STEPS = [
    { path: "/dashboard", title: "Welcome to your portfolio",
      body: "This is a local ledger. You record what you bought, sold and received, and enter prices. The app works out holdings, value and return from those. The tour takes about a minute and opens a few pages as it goes." },
    { path: "/dashboard", target: "nav", title: "Getting around",
      body: "Set up in this order: Instruments, then Transactions, then Prices. The dashboard is built from those three. Reconcile checks the total against your own spreadsheet." },
    { path: "/dashboard", target: "kpis", title: "Your headline figures",
      body: "Total value is in your base currency. Total return is time-weighted, so deposits and withdrawals don't count as gains. Dividends are already inside the value, not added on top." },
    { path: "/dashboard", target: "chart", title: "Value over time",
      body: "Switch between value and total return, and pick a range. Days without a complete set of prices show as gaps, not flat lines. △ marks a transfer in or out. The table under the chart lists every day." },
    { path: "/dashboard", target: "allocation", title: "Where your money sits",
      body: "Each platform's or asset class's share of the total. The grey box names the FX rate used and how much a one-peso move in it changes the total." },
    { path: "/dashboard", target: "holdings", title: "Holdings",
      body: "Each row is computed from your transactions, never typed in. ⚠ stale means the price is older than the last trading day. Group by platform or asset class, and use the buttons here to enter prices or record a trade." },
    { path: "/dashboard", target: "recent", title: "Recent activity",
      body: "The latest transactions. Rows marked ↳ 🔒 are cash legs the app generates for you. To change one, edit its parent transaction.",
      next: "Next opens Instruments" },
    { path: "/instruments", target: "add-instrument", title: "Step 1 · Add an instrument",
      body: "An instrument is anything you hold on a platform: a stock, ETF, fund or coin. Add each one once. Cash balances for each platform are created for you.",
      next: "Next opens Transactions" },
    { path: "/transactions", target: "record-actions", title: "Step 2 · Record transactions",
      body: "Record buys, sells, dividends, rewards, fees and transfers. Each trade creates its own cash leg. Record the deposit as a transfer first, so platform cash doesn't go negative.",
      next: "Next opens Prices" },
    { path: "/prices", target: "price-actions", title: "Step 3 · Enter prices",
      body: "Prices are entered by hand for now. Bulk entry updates every holding for one date. Add a USD/PHP rate too, or USD holdings are left out of the total rather than counted as zero.",
      next: "Next opens Reconcile" },
    { path: "/reconciliation", target: "reconcile-form", title: "Check the numbers",
      body: "Enter the total from an independent spreadsheet built with the same prices and FX rate. The app records the difference, so you can explain it in a note.",
      next: "Next opens Settings" },
    { path: "/settings", target: "preferences", title: "Preferences",
      body: "Set the display name, base currency and appearance. Under Local data you can export a backup of the database." },
    { path: "/settings", target: "tour-button", title: "You're set",
      body: "Replay this tour any time from the Tour button. Start by adding your first instrument." },
  ];

  const body = document.body;
  const PAD = 6, GAP = 12, EDGE = 16;
  let index = -1, ui = null, returnFocus = null;

  const $ = s => document.querySelector(s);
  const targetOf = step => (step.target ? $(`[data-tour="${step.target}"]`) : null);

  const markSeen = () => {
    const url = body.dataset.tourSeenUrl;
    if (!url || body.dataset.tourAutostart !== "1") return;
    body.dataset.tourAutostart = "0";
    fetch(url, { method: "POST", credentials: "same-origin" }).catch(() => {});
  };

  const build = () => {
    const backdrop = document.createElement("div");
    backdrop.className = "tour-backdrop";
    const spot = document.createElement("div");
    spot.className = "tour-spot";
    const pop = document.createElement("div");
    pop.className = "tour-pop";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-modal", "false");
    pop.setAttribute("aria-labelledby", "tourTitle");
    pop.setAttribute("aria-describedby", "tourBody");
    pop.innerHTML = `
      <div class="tour-arrow" aria-hidden="true"></div>
      <div class="tour-step" id="tourCount"></div>
      <h3 id="tourTitle"></h3>
      <p id="tourBody"></p>
      <div class="tour-dots" aria-hidden="true"></div>
      <div class="tour-foot">
        <button type="button" class="link tour-skip">Skip tour</button>
        <div class="row">
          <button type="button" class="btn tour-back">Back</button>
          <button type="button" class="btn primary tour-next">Next</button>
        </div>
      </div>
      <div class="tour-hint" id="tourHint"></div>`;
    pop.querySelector(".tour-dots").innerHTML = STEPS.map(() => "<i></i>").join("");
    pop.querySelector(".tour-skip").addEventListener("click", end);
    pop.querySelector(".tour-back").addEventListener("click", () => go(index - 1));
    pop.querySelector(".tour-next").addEventListener("click", () => go(index + 1));
    // The backdrop swallows clicks so the page can't change under a coachmark.
    backdrop.addEventListener("click", e => e.stopPropagation());
    document.body.append(backdrop, spot, pop);
    addEventListener("keydown", onKey);
    addEventListener("resize", place);
    addEventListener("scroll", place, { passive: true });
    return { backdrop, spot, pop };
  };

  const onKey = e => {
    if (!ui) return;
    if (e.key === "Escape") { e.preventDefault(); end(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); go(index + 1); }
    else if (e.key === "ArrowLeft" && index > 0) { e.preventDefault(); go(index - 1); }
  };

  const place = () => {
    if (!ui) return;
    const { spot, pop } = ui;
    const step = STEPS[index];
    const target = targetOf(step);
    const vw = document.documentElement.clientWidth, vh = innerHeight;
    const arrow = pop.querySelector(".tour-arrow");
    pop.classList.remove("docked", "centered", "above", "below");

    if (!target) {
      spot.classList.add("none");
      pop.classList.add("centered");
      pop.style.left = pop.style.top = "";
      return;
    }
    spot.classList.remove("none");
    const r = target.getBoundingClientRect();
    const box = {
      left: Math.max(r.left - PAD, 4), top: Math.max(r.top - PAD, 4),
      right: Math.min(r.right + PAD, vw - 4), bottom: Math.min(r.bottom + PAD, vh - 4),
    };
    Object.assign(spot.style, {
      left: box.left + "px", top: box.top + "px",
      width: Math.max(box.right - box.left, 0) + "px", height: Math.max(box.bottom - box.top, 0) + "px",
    });

    const pw = pop.offsetWidth, ph = pop.offsetHeight;
    const below = vh - box.bottom - GAP, above = box.top - GAP;
    // On narrow screens, or when the target fills the view, dock the card at the bottom.
    if (vw < 560 || (below < ph && above < ph)) {
      pop.classList.add("docked");
      pop.style.left = pop.style.top = "";
      return;
    }
    const side = below >= ph ? "below" : "above";
    pop.classList.add(side);
    const left = Math.min(Math.max(box.left, EDGE), vw - pw - EDGE);
    const top = side === "below" ? box.bottom + GAP : box.top - GAP - ph;
    pop.style.left = left + "px";
    pop.style.top = top + "px";
    const anchor = Math.min(Math.max((Math.max(box.left, 0) + Math.min(box.right, vw)) / 2, left + 20), left + pw - 20);
    arrow.style.left = anchor - left - 6 + "px";
  };

  const render = () => {
    const step = STEPS[index];
    const { pop } = ui;
    const last = index === STEPS.length - 1;
    pop.querySelector("#tourCount").textContent = `${index + 1} of ${STEPS.length}`;
    pop.querySelector("#tourTitle").textContent = step.title;
    pop.querySelector("#tourBody").textContent = step.body;
    pop.querySelector("#tourHint").textContent = step.next || "";
    pop.querySelector(".tour-back").hidden = index === 0;
    pop.querySelector(".tour-skip").hidden = last;
    const next = pop.querySelector(".tour-next");
    next.textContent = last ? "Finish" : index === 0 ? "Start tour" : "Next";
    pop.querySelectorAll(".tour-dots i").forEach((dot, i) => dot.classList.toggle("on", i === index));

    const target = targetOf(step);
    if (target) {
      const tall = target.getBoundingClientRect().height > innerHeight * 0.55;
      // Jump rather than smooth-scroll, so the spotlight never trails its target.
      target.scrollIntoView({ block: tall ? "start" : "center", behavior: "auto" });
    }
    place();
    requestAnimationFrame(place);
    next.focus({ preventScroll: true });
  };

  const go = to => {
    if (to < 0) return;
    if (to >= STEPS.length) { end(); return; }
    const step = STEPS[to];
    if (step.path !== location.pathname) {
      location.href = `${step.path}?tour=${to}`;
      return;
    }
    index = to;
    if (!ui) ui = build();
    render();
  };

  function end() {
    if (!ui) return;
    removeEventListener("keydown", onKey);
    removeEventListener("resize", place);
    removeEventListener("scroll", place);
    Object.values(ui).forEach(node => node.remove());
    ui = null;
    index = -1;
    markSeen();
    const back = returnFocus || $("[data-tour-start]");
    if (back) back.focus({ preventScroll: true });
    returnFocus = null;
  }

  const start = (from = 0) => {
    markSeen();
    go(from);
  };

  document.querySelectorAll("[data-tour-start]").forEach(button =>
    button.addEventListener("click", () => { returnFocus = button; if (ui) end(); start(0); })
  );

  // Resume a tour that navigated here, then tidy the URL.
  const params = new URLSearchParams(location.search);
  const resume = params.get("tour");
  if (resume !== null) {
    params.delete("tour");
    const query = params.toString();
    history.replaceState(null, "", location.pathname + (query ? `?${query}` : "") + location.hash);
    const at = Number(resume);
    if (Number.isInteger(at) && STEPS[at] && STEPS[at].path === location.pathname) go(at);
  } else if (body.dataset.tourAutostart === "1" && location.pathname === "/dashboard") {
    start(0);
  }
})();
