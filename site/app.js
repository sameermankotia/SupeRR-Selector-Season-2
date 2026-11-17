/* Reliable Under Pressure — dashboard logic.
   Hand-rolled SVG charts: no library, no build step, works from file:// too. */
(function () {
  "use strict";
  var D = window.RR_DATA;
  var C = { c1: "#DD3189", c2: "#C08A1E", c3: "#29A092", c4: "#7A6FD2",
            grid: "#1C2756", axis: "#2B3870", ink3: "#737FB0", gold: "#F4C542" };
  var NS = "http://www.w3.org/2000/svg";
  var tip = document.getElementById("tip");

  function el(t, a, kids) {
    var e = document.createElementNS(NS, t);
    for (var k in a) if (a[k] != null) e.setAttribute(k, a[k]);
    (kids || []).forEach(function (c) { e.appendChild(c); });
    return e;
  }
  function txt(s, a) { var e = el("text", a); e.textContent = s; return e; }
  function h(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function showTip(evt, html) {
    tip.innerHTML = html;
    tip.style.opacity = 1;
    var pad = 14;
    var x = evt.clientX + pad, y = evt.clientY + pad;
    var r = tip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
    tip.style.left = (x + scrollX) + "px";
    tip.style.top = (y + scrollY) + "px";
  }
  function hideTip() { tip.style.opacity = 0; }
  function hook(node, html) {
    node.addEventListener("mousemove", function (e) { showTip(e, html); });
    node.addEventListener("mouseleave", hideTip);
  }
  function svg(w, hh) {
    return el("svg", { viewBox: "0 0 " + w + " " + hh, class: "chart",
                       preserveAspectRatio: "xMidYMid meet", width: "100%" });
  }

  /* ---------------- hero stats ---------------- */
  (function () {
    var m = D.meta;
    [[m.deliveries.toLocaleString(), "deliveries analysed"],
     [m.matches.toLocaleString(), "matches, IPL 2022–26 + T20I"],
     ["<em>" + m.wp_auc_chase.toFixed(3) + "</em>", "chase win-probability AUC"],
     [m.press_share_bat + "%", "flagged as pressure"],
     ["<em>" + m.state_accuracy + "%</em>", "match-state accuracy"],
     [m.pool_bat + " / " + m.pool_bowl, "eligible batters / bowlers"]
    ].forEach(function (s) {
      var d = h("div", "stat");
      d.appendChild(h("div", "k tnum", s[0]));
      d.appendChild(h("div", "l", s[1]));
      document.getElementById("statbar").appendChild(d);
    });
  })();

  /* ---------------- availability ---------------- */
  var AV = D.avail;
  function statusOf(side, name) {
    var m = AV[side === "batters" || side === "bat" ? "bat" : "bowl"].status;
    return m[name] || { status: "unlisted", team: null };
  }
  function badge(st) {
    if (st.status === "released")
      return '<span class="pill free">released · ' + esc(st.team) + '</span>';
    if (st.status === "unlisted")
      return '<span class="pill free">available</span>';
    if (st.team === "RR")
      return '<span class="pill rr">at RR</span>';
    return '<span class="pill lock">' + esc(st.team) + '</span>';
  }

  (function () {
    var a = document.getElementById("availalert");
    a.innerHTML = '<span class="ic">⚠</span><div>Only <b>' + AV.bat.n_available +
      ' of ' + AV.bat.n_eligible + '</b> eligible batters and <b>' + AV.bowl.n_available +
      ' of ' + AV.bowl.n_eligible + '</b> eligible bowlers are actually available at the 2027 ' +
      'auction — the rest have been retained. Every row below is tagged with its real status, ' +
      'and the <a href="#board">auction board</a> ranks only who RR can genuinely bid for.</div>';
  })();

  /* ---------------- ranking lists ---------------- */
  function rankCard(side, title, sub) {
    var card = h("div", "rank-card");
    var head = h("div", "rank-head");
    head.appendChild(h("h3", null, title));
    head.appendChild(h("span", null, sub));
    card.appendChild(head);
    D[side].forEach(function (p) {
      var b = h("button", "rk");
      b.type = "button";
      var st = statusOf(side, p.name);
      b.innerHTML =
        '<span class="n tnum">' + p.rank + '</span>' +
        '<span class="nm">' + esc(p.name) + ' ' + badge(st) +
          '<small>' + (p.nation === "unknown" ? "" : esc(p.nation) + ' · ') +
            p.press_balls + ' pressure balls</small></span>' +
        '<span class="v tnum">' + Math.round(p.p_top10 * 100) + '%</span>' +
        '<span class="chev" aria-hidden="true">›</span>';
      b.setAttribute("aria-label", "View " + p.name);
      b.addEventListener("click", function () {
        select(side === "batters" ? "bat" : "bowl", p.name, true);
      });
      card.appendChild(b);
    });
    return card;
  }
  document.getElementById("ranks").append(
    rankCard("batters", "Top 10 batters", "P(top 10)"),
    rankCard("bowlers", "Top 10 bowlers", "P(top 10)"));

  /* ---------------- RR purse + auction board ---------------- */
  (function () {
    [["₹" + AV.purse.RR + " cr", "RR purse at the auction"],
     [String(AV.slots.RR), "squad slots to fill"],
     [String(AV.overseas_slots.RR), "of them overseas"],
     ["<em>" + AV.bat.n_available + "</em>", "eligible batters available"],
     ["<em>" + AV.bowl.n_available + "</em>", "eligible bowlers available"],
     [AV.as_of.slice(8) + " Nov", "retention lists as of"]
    ].forEach(function (s2) {
      var d = h("div", "stat");
      d.appendChild(h("div", "k tnum", s2[0]));
      d.appendChild(h("div", "l", s2[1]));
      document.getElementById("rrbar").appendChild(d);
    });

    [["bat", "Batters available", "The market is almost empty — this is the finding"],
     ["bowl", "Bowlers available", "Far deeper, and it includes a top-5 pressure bowler"]
    ].forEach(function (cfg) {
      var side = cfg[0], card = h("div", "rank-card");
      var head = h("div", "rank-head");
      head.appendChild(h("h3", null, cfg[1]));
      head.appendChild(h("span", null, "P(top 10)"));
      card.appendChild(head);
      card.appendChild(h("div", "csub", null)).textContent =
        cfg[2] + " — numbered by rank in the full eligible pool";
      AV[side].board.slice(0, 10).forEach(function (p) {
        var b = h("button", "rk");
        b.type = "button";
        var st = { status: p.status, team: p.team };
        b.innerHTML =
          '<span class="n tnum">' + p.rank + '</span>' +
          '<span class="nm">' + esc(p.name) + ' ' + badge(st) +
            '<small>' + p.press_balls + ' pressure balls · value ' +
            (p.press_value >= 0 ? "+" : "") + p.press_value.toFixed(3) + '</small></span>' +
          '<span class="v tnum">' + Math.round(p.p_top10 * 100) + '%</span>' +
          '<span class="chev" aria-hidden="true">›</span>';
        b.addEventListener("click", function () { select(side, p.name, true); });
        card.appendChild(b);
      });
      document.getElementById("boards").appendChild(card);
    });
    document.getElementById("availsrc").textContent =
      "Retention and release lists as reported on " + AV.as_of +
      " by Yahoo Sports and M9 News; India TV could not be read. " + AV.caveat +
      " Players in neither list had no IPL 2026 contract and are treated as available " +
      "but unconfirmed.";
  })();

  /* ---------------- grouped bar ---------------- */
  function groupedBar(node, rows, keys, labels, colors, fmt, unit) {
    var W = 520, H = 250, L = 46, R = 14, T = 12, B = 42;
    var s = svg(W, H), max = 0;
    rows.forEach(function (r) { keys.forEach(function (k) { max = Math.max(max, r[k]); }); });
    max *= 1.18;
    var iw = W - L - R, ih = H - T - B, bw = iw / rows.length;
    for (var i = 0; i <= 4; i++) {
      var y = T + ih - (ih * i / 4);
      s.appendChild(el("line", { x1: L, x2: W - R, y1: y, y2: y, stroke: C.grid, "stroke-width": 1 }));
      s.appendChild(txt(fmt(max * i / 4), { x: L - 8, y: y + 4, "text-anchor": "end" }));
    }
    rows.forEach(function (r, i) {
      var gw = bw * 0.62, each = gw / keys.length;
      keys.forEach(function (k, j) {
        var hgt = Math.max(ih * r[k] / max, 1);
        var x = L + bw * i + (bw - gw) / 2 + j * each;
        var rect = el("rect", { x: x + 1.5, y: T + ih - hgt, width: each - 3, height: hgt,
                                fill: colors[j], rx: 3 });
        hook(rect, "<b>" + esc(r.phase) + "</b><br>" + labels[j] + ": " + fmt(r[k]) + unit);
        s.appendChild(rect);
        s.appendChild(txt(fmt(r[k]), { x: x + each / 2, y: T + ih - hgt - 6,
                                       "text-anchor": "middle", class: "val" }));
      });
      s.appendChild(txt(r.phase, { x: L + bw * i + bw / 2, y: H - B + 20,
                                   "text-anchor": "middle", class: "lbl" }));
    });
    s.appendChild(el("line", { x1: L, x2: W - R, y1: T + ih, y2: T + ih, stroke: C.axis }));
    node.appendChild(s);
    var lg = h("div", "legend");
    keys.forEach(function (k, j) {
      lg.appendChild(h("span", null, '<i style="background:' + colors[j] + '"></i>' + labels[j]));
    });
    node.appendChild(lg);
  }
  groupedBar(document.getElementById("c-share"), D.share, ["bat", "bowl"],
             ["Batting pressure", "Bowling pressure"], [C.c1, C.c2],
             function (v) { return v.toFixed(0); }, "%");
  groupedBar(document.getElementById("c-lev"), D.leverage, ["set", "chase"],
             ["1st innings (setting)", "2nd innings (chasing)"], [C.c4, C.c3],
             function (v) { return v.toFixed(2); }, "");

  /* ---------------- validation deciles ---------------- */
  function decileBar(node, rows, key, fmt, unit, caption) {
    var W = 520, H = 250, L = 46, R = 14, T = 12, B = 46;
    var s = svg(W, H);
    var max = Math.max.apply(null, rows.map(function (r) { return r[key]; })) * 1.16;
    var iw = W - L - R, ih = H - T - B, bw = iw / rows.length;
    for (var i = 0; i <= 4; i++) {
      var y = T + ih - (ih * i / 4);
      s.appendChild(el("line", { x1: L, x2: W - R, y1: y, y2: y, stroke: C.grid }));
      s.appendChild(txt(fmt(max * i / 4), { x: L - 8, y: y + 4, "text-anchor": "end" }));
    }
    rows.forEach(function (r, i) {
      var hgt = Math.max(ih * r[key] / max, 1);
      // one ramp step per decile: light (low pressure) to RR pink (high)
      var t = i / (rows.length - 1);
      var col = "rgb(" + Math.round(70 + t * 151) + "," + Math.round(96 - t * 47) +
                "," + Math.round(160 - t * 23) + ")";
      var rect = el("rect", { x: L + bw * i + bw * 0.14, y: T + ih - hgt,
                              width: bw * 0.72, height: hgt, fill: col, rx: 3 });
      hook(rect, "Decile <b>" + r.decile + "</b> of 10<br>" + caption + ": " +
                 fmt(r[key]) + unit + "<br>strike rate " + r.strike_rate);
      s.appendChild(rect);
      if (i === 0 || i === rows.length - 1)
        s.appendChild(txt(fmt(r[key]), { x: L + bw * i + bw / 2, y: T + ih - hgt - 6,
                                         "text-anchor": "middle", class: "val" }));
      s.appendChild(txt(r.decile, { x: L + bw * i + bw / 2, y: H - B + 18,
                                    "text-anchor": "middle" }));
    });
    s.appendChild(el("line", { x1: L, x2: W - R, y1: T + ih, y2: T + ih, stroke: C.axis }));
    s.appendChild(txt("← less pressure", { x: L, y: H - 6, class: "lbl" }));
    s.appendChild(txt("more pressure →", { x: W - R, y: H - 6,
                                           "text-anchor": "end", class: "lbl" }));
    node.appendChild(s);
  }
  decileBar(document.getElementById("c-vbat"), D.validation.bat, "runs_per_wkt",
            function (v) { return v.toFixed(0); }, "", "Runs per wicket");
  decileBar(document.getElementById("c-vbowl"), D.validation.bowl, "runs_per_ball",
            function (v) { return v.toFixed(2); }, "", "Runs per ball");

  /* ---------------- quadrant scatter ---------------- */
  (function () {
    var node = document.getElementById("c-quad");
    var W = 1060, H = 420, L = 58, R = 20, T = 16, B = 52;
    var s = svg(W, H);
    var pts = D.pool.bat.map(function (p) { return { p: p, side: "bat" }; })
      .concat(D.pool.bowl.map(function (p) { return { p: p, side: "bowl" }; }));
    var xs = pts.map(function (o) { return o.p.res; });
    var ys = pts.map(function (o) { return o.p.press; });
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var padx = (x1 - x0) * .08, pady = (y1 - y0) * .1;
    x0 -= padx; x1 += padx; y0 -= pady; y1 += pady;
    var iw = W - L - R, ih = H - T - B;
    function X(v) { return L + iw * (v - x0) / (x1 - x0); }
    function Y(v) { return T + ih - ih * (v - y0) / (y1 - y0); }
    for (var i = 0; i <= 4; i++) {
      var yy = T + ih * i / 4, xx = L + iw * i / 4;
      s.appendChild(el("line", { x1: L, x2: W - R, y1: yy, y2: yy, stroke: C.grid }));
      s.appendChild(el("line", { x1: xx, x2: xx, y1: T, y2: T + ih, stroke: C.grid }));
      s.appendChild(txt((y1 - (y1 - y0) * i / 4).toFixed(2),
                        { x: L - 9, y: yy + 4, "text-anchor": "end" }));
      s.appendChild(txt((x0 + (x1 - x0) * i / 4).toFixed(2),
                        { x: xx, y: T + ih + 18, "text-anchor": "middle" }));
    }
    s.appendChild(el("line", { x1: X(0), x2: X(0), y1: T, y2: T + ih,
                               stroke: C.axis, "stroke-dasharray": "4 4" }));
    s.appendChild(txt("worse under pressure than their own normal  ←",
                      { x: X(0) - 10, y: T + 16, "text-anchor": "end", class: "lbl" }));
    s.appendChild(txt("→  rises above their own normal",
                      { x: X(0) + 10, y: T + 16, class: "lbl" }));
    var top = {};
    D.batters.forEach(function (p) { top["bat" + p.name] = p.rank; });
    D.bowlers.forEach(function (p) { top["bowl" + p.name] = p.rank; });
    pts.forEach(function (o) {
      var rank = top[o.side + o.p.name];
      var c = o.side === "bat" ? C.c1 : C.c3;
      var g = el("circle", { cx: X(o.p.res), cy: Y(o.p.press), r: rank ? 7 : 4,
                             fill: rank ? c : "#3A4780", "fill-opacity": rank ? 1 : .62,
                             stroke: rank ? "#0F1733" : "none", "stroke-width": 1.6 });
      hook(g, "<b>" + esc(o.p.name) + "</b>" + (rank ? " — rank " + rank : "") +
              "<br>" + (o.side === "bat" ? "Batter" : "Bowler") +
              "<br>pressure value " + o.p.press.toFixed(3) +
              "<br>resilience " + (o.p.res >= 0 ? "+" : "") + o.p.res.toFixed(3) +
              "<br>" + o.p.balls + " pressure balls");
      g.style.cursor = rank ? "pointer" : "default";
      if (rank) g.addEventListener("click", function () { select(o.side, o.p.name, true); });
      s.appendChild(g);
    });
    s.appendChild(el("line", { x1: L, x2: W - R, y1: T + ih, y2: T + ih, stroke: C.axis }));
    s.appendChild(el("line", { x1: L, x2: L, y1: T, y2: T + ih, stroke: C.axis }));
    s.appendChild(txt("Resilience  (pressure minus own baseline, runs/ball)",
                      { x: L + iw / 2, y: H - 14, "text-anchor": "middle", class: "lbl" }));
    s.appendChild(txt("Pressure performance (runs/ball)",
                      { x: -(T + ih / 2), y: 16, transform: "rotate(-90)",
                        "text-anchor": "middle", class: "lbl" }));
    node.appendChild(s);
    var lg = h("div", "legend");
    lg.appendChild(h("span", null, '<i style="background:' + C.c1 + '"></i>Top 10 batters'));
    lg.appendChild(h("span", null, '<i style="background:' + C.c3 + '"></i>Top 10 bowlers'));
    lg.appendChild(h("span", null, '<i style="background:#3A4780"></i>Rest of the eligible pool'));
    node.appendChild(lg);
  })();

  /* ---------------- RR squad vs pool ---------------- */
  (function () {
    var node = document.getElementById("c-rr");
    var sides = [{ key: "batters", pool: "bat", label: "Batters", col: C.c1 },
                 { key: "bowlers", pool: "bowl", label: "Bowlers", col: C.c3 }];
    var wrap = h("div", "grid2");
    sides.forEach(function (sd) {
      var rows = D.rr[sd.key].slice().sort(function (a, b) { return a.rank - b.rank; });
      var pool = D.pool[sd.pool];
      var W = 520, rowH = 30, T = 54, B = 44, L = 118, R = 46;
      var H = T + rows.length * rowH + B;
      var s = svg(W, H);
      var vs = pool.map(function (p) { return p.press; });
      var x0 = Math.min.apply(null, vs), x1 = Math.max.apply(null, vs);
      var pad = (x1 - x0) * .07; x0 -= pad; x1 += pad;
      function X(v) { return L + (W - L - R) * (v - x0) / (x1 - x0); }
      s.appendChild(txt("all " + pool.length + " eligible players",
                        { x: L, y: 16, class: "lbl" }));
      pool.forEach(function (p, i) {
        s.appendChild(el("circle", { cx: X(p.press), cy: 30 + ((i * 7) % 11) - 5, r: 3,
                                     fill: "#3A4780", "fill-opacity": .6 }));
      });
      rows.forEach(function (r, i) {
        var y = T + i * rowH + rowH / 2;
        s.appendChild(el("line", { x1: L, x2: X(r.press_value), y1: y, y2: y,
                                   stroke: C.grid, "stroke-width": 1.5 }));
        var c = el("circle", { cx: X(r.press_value), cy: y, r: 6.5, fill: sd.col,
                               stroke: "#0F1733", "stroke-width": 1.5 });
        hook(c, "<b>" + esc(r.name) + "</b><br>rank " + r.rank + " of " + r.of +
                "<br>pressure value " + r.press_value.toFixed(3));
        s.appendChild(c);
        s.appendChild(txt(r.name, { x: L - 10, y: y + 4, "text-anchor": "end", class: "lbl" }));
        s.appendChild(txt(r.rank + "/" + r.of,
                          { x: X(r.press_value) + 12, y: y + 4, class: "val" }));
      });
      s.appendChild(el("line", { x1: L, x2: W - R, y1: H - B + 6, y2: H - B + 6, stroke: C.axis }));
      [0, .5, 1].forEach(function (f) {
        var v = x0 + (x1 - x0) * f;
        s.appendChild(txt(v.toFixed(2), { x: X(v), y: H - B + 22, "text-anchor": "middle" }));
      });
      s.appendChild(txt("Pressure performance (runs/ball) →",
                        { x: W - R, y: H - B + 38, "text-anchor": "end", class: "lbl" }));
      var box = h("div");
      box.appendChild(h("div", "ctitle", sd.label));
      box.appendChild(s);
      wrap.appendChild(box);
    });
    node.appendChild(wrap);
  })();

  /* ---------------- gap cards ---------------- */
  [["Critical", "Finishing — one real option",
    "RR have just released Shimron Hetmyer, whom this model independently rated 34th of 39 under pressure. Behind Riyan Parag (7th) the middle order now rates 38th (Dhruv Jurel).",
    "<b>Andre Russell</b> is the strongest pressure performer in the whole dataset and one of only five eligible batters actually available. Beyond him the board drops to <b>Liam Livingstone</b> (#28) and <b>Moeen Ali</b> (#26) — a steep fall. Spend here first."],
   ["Unresolved", "Spin — the market cannot fix it",
    "Ravi Bishnoi, RR's frontline spinner, rates 49th of 50 and has been retained. Every spinner above him in the pool — Narine, Axar, Rashid, Krunal — is retained elsewhere.",
    "The best available spin is <b>Maheesh Theekshana</b> (#24) and <b>Wanindu Hasaranga</b> (#27), both a clear step down from the top. This gap realistically carries into next season; plan around it rather than overpaying."],
   ["High", "Death bowling — the one clean win",
    "Archer (8th of 50) aside, RR's death unit was Tushar Deshpande (34th, now released by RR) and Sandeep Sharma (44th, retained).",
    "<b>Matheesha Pathirana</b> is released by KKR and is the most actionable name in this analysis: a top-five pressure bowler, 67% of his work at the death, best strike rate in the pool. <b>Mustafizur Rahman</b> (#13) and <b>Avesh Khan</b> (#20) are the fallbacks."]
  ].forEach(function (g) {
    var c = h("div", "gap-card");
    c.appendChild(h("span", "sev", g[0] + " priority"));
    c.appendChild(h("h4", null, g[1]));
    c.appendChild(h("p", null, g[2]));
    c.appendChild(h("div", "sol", g[3]));
    document.getElementById("gaps").appendChild(c);
  });

  /* ---------------- reliability table ---------------- */
  (function () {
    var r = D.reliability, t = document.getElementById("reltable");
    t.innerHTML = "<thead><tr><th>Quantity</th><th class='num'>Split-half r</th>" +
                  "<th class='num'>Full-sample</th></tr></thead>";
    var tb = document.createElement("tbody");
    [["Batting — absolute pressure value", r.bat.absolute, r.bat.absolute_full],
     ["Batting — resilience delta", r.bat.resilience, r.bat.resilience_full],
     ["Batting — final composite", r.bat.final_rating, r.bat.final_rating_full],
     ["Bowling — absolute pressure value", r.bowl.absolute, r.bowl.absolute_full],
     ["Bowling — resilience delta", r.bowl.resilience, r.bowl.resilience_full],
     ["Bowling — final composite", r.bowl.final_rating, r.bowl.final_rating_full]
    ].forEach(function (row) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + row[0] + "</td><td class='num tnum'>" +
        (row[1] >= 0 ? "+" : "") + row[1].toFixed(3) + "</td><td class='num tnum'>" +
        row[2].toFixed(3) + "</td>";
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    document.getElementById("wpa-line").innerHTML =
      "Every player was also scored in <b style='color:var(--ink)'>win-probability added</b> — " +
      "a different currency built from match outcomes rather than runs. The two rank players " +
      "consistently: Spearman <b style='color:var(--gold)'>" + r.wpa_bat.toFixed(3) +
      "</b> for batters and <b style='color:var(--gold)'>" + r.wpa_bowl.toFixed(3) +
      "</b> for bowlers. Resilience is weighted " + Math.round(r.weights.bat[1] * 100) +
      "% for batters and " + Math.round(r.weights.bowl[1] * 100) +
      "% for bowlers, because it measurably does not repeat for bowlers.";
  })();

  /* ---------------- player explorer ---------------- */
  var cur = { side: "bat", name: D.batters[0].name };
  function arr(side) { return side === "bat" ? D.batters : D.bowlers; }
  /* top-10 cards carry the written notes; board records cover every other
     available player so the auction board stays clickable */
  function find(side, name) {
    var c = arr(side).filter(function (x) { return x.name === name; })[0];
    if (c) return c;
    return AV[side].board.filter(function (x) { return x.name === name; })[0];
  }

  function delta(a, b, goodUp) {
    if (a == null || b == null) return "";
    var d = a - b, up = d > 0, good = goodUp ? up : !up;
    return '<span class="' + (good ? "up" : "dn") + '">' +
           (up ? "▲" : "▼") + " " + Math.abs(d).toFixed(1) +
           "</span> vs " + Number(b).toFixed(1);
  }
  function metric(label, val, sub) {
    return '<div class="m"><div class="l">' + label + '</div><div class="v tnum">' +
           val + '</div><div class="d">' + (sub || "") + '</div></div>';
  }

  function renderPanel() {
    var p = find(cur.side, cur.name);
    if (!p) return;
    var isBat = cur.side === "bat";
    var m = isBat
      ? metric("Strike rate", p.sr_press, delta(p.sr_press, p.sr_base, true)) +
        metric("Boundary %", p.bdry_press, p.bdry_base != null ?
               delta(p.bdry_press, p.bdry_base, true) : "under pressure") +
        metric("Balls / dismissal", p.bpd_press, delta(p.bpd_press, p.bpd_base, true)) +
        metric("At the death", p.death_share + "%", "of pressure balls") +
        metric("vs pace / spin", p.sr_pace + " / " + p.sr_spin, "pressure strike rate") +
        metric("Chasing", (p.chase_share == null ? "—" : p.chase_share + "%"),
               "of pressure balls")
      : metric("Economy", p.econ_press, delta(p.econ_press, p.econ_base, false)) +
        metric("Dot %", p.dot_press, p.dot_base != null ?
               delta(p.dot_press, p.dot_base, true) : "under pressure") +
        metric("Balls / wicket", p.bpw_press, delta(p.bpw_press, p.bpw_base, false)) +
        metric("Powerplay", p.pp_share + "%", "of pressure balls") +
        metric("At the death", p.death_share + "%", "of pressure balls") +
        metric("Boundary % given", p.bdry_conceded_press == null ? "—"
               : p.bdry_conceded_press, "under pressure");

    var iplWarn = p.ipl_press_balls < 150
      ? ' <span style="color:var(--gold)">· thin IPL sample</span>' : "";
    var st = statusOf(cur.side, p.name);
    var alts = (AV[cur.side].alternatives || {})[p.name] || [];
    var altHtml = "";
    if (!(st.status === "released" || st.status === "unlisted")) {
      altHtml = '<div class="alts"><h4>' +
        (st.team === "RR" ? "Already at RR — comparable options if cover is needed"
                          : "Retained by " + esc(st.team) + " — closest available alternatives") +
        '</h4>' +
        (alts.length ? alts.map(function (a) {
          return '<div class="alt"><span class="an">' + esc(a.name) +
            ' <span class="pill free">' +
            (a.status === "released" ? "released · " + esc(a.team) : "available") +
            '</span></span>' +
            '<span class="am">' + a.role_match + ' role match</span>' +
            '<span class="av">#' + a.rank + ' · ' +
            (a.press_value >= 0 ? "+" : "") + a.press_value.toFixed(3) + '</span></div>';
        }).join("") : '<p class="note">No comparable player is available in this role.</p>') +
        '</div>';
    }

    document.getElementById("panel").innerHTML =
      '<div class="p-top">' +
        '<div class="p-rank tnum">' + p.rank + '</div>' +
        '<div class="p-id"><h3>' + esc(p.name) +
          (p.at_rr ? ' <span class="tag">already at RR</span>' : '') + '</h3>' +
          '<div class="meta">' +
          (!p.nation || p.nation === "unknown" ? "" : esc(p.nation) + ' · ') +
          (isBat ? "batter" : esc(p.type || "bowler")) +
          ' · ' + p.press_balls + ' pressure balls (' + p.ipl_press_balls + ' IPL)' + iplWarn +
          (p.matches ? ' · ' + p.matches + ' matches' : '') + '</div>' +
          '<div style="margin-top:7px">' + badge(st) + '</div></div>' +
        '<div class="p-conf"><div class="b tnum">' + Math.round(p.p_top10 * 100) + '%</div>' +
          '<div class="l">bootstrap P(top 10)</div></div>' +
      '</div>' +
      '<div class="mgrid">' + m + '</div>' +
      (p.read ? '<p class="note">' + esc(p.read) + '</p>' : '') +
      (p.fit ? '<div class="fit"><b>For RR:</b> ' + esc(p.fit) + '</div>' : '') + altHtml;
  }

  function renderList() {
    var list = document.getElementById("plist");
    list.innerHTML = "";
    var inTop = arr(cur.side).some(function (x) { return x.name === cur.name; });
    if (!inTop) {
      var hdr = h("div", "pitem");
      hdr.setAttribute("aria-current", "true");
      hdr.innerHTML = '<span class="r tnum">★</span><span>' + esc(cur.name) +
                      '<br><small style="color:var(--ink-3)">from the auction board</small></span>';
      list.appendChild(hdr);
    }
    arr(cur.side).forEach(function (p) {
      var b = h("button", "pitem");
      b.type = "button";
      b.setAttribute("aria-current", p.name === cur.name ? "true" : "false");
      b.innerHTML = '<span class="r tnum">' + p.rank + '</span><span>' + esc(p.name) + '</span>';
      b.addEventListener("click", function () { select(cur.side, p.name, false); });
      list.appendChild(b);
    });
  }

  function select(side, name, scroll) {
    cur.side = side; cur.name = name;
    document.getElementById("tab-bat").setAttribute("aria-pressed", side === "bat");
    document.getElementById("tab-bowl").setAttribute("aria-pressed", side === "bowl");
    renderList(); renderPanel();
    if (scroll) document.getElementById("players").scrollIntoView({ block: "start" });
  }
  document.getElementById("tab-bat").addEventListener("click", function () {
    select("bat", D.batters[0].name, false);
  });
  document.getElementById("tab-bowl").addEventListener("click", function () {
    select("bowl", D.bowlers[0].name, false);
  });
  select("bat", D.batters[0].name, false);
})();
