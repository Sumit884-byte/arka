(function () {
  const header = document.querySelector(".site-header");
  const menuToggle = document.querySelector(".menu-toggle");
  const navMobile = document.querySelector(".nav-mobile");
  const copyBtn = document.getElementById("copy-install");
  const installCmd = document.getElementById("install-cmd");

  function onScroll() {
    if (!header) return;
    header.classList.toggle("scrolled", window.scrollY > 8);
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  if (menuToggle && navMobile) {
    menuToggle.addEventListener("click", () => {
      const open = navMobile.classList.toggle("open");
      menuToggle.setAttribute("aria-expanded", String(open));
      menuToggle.textContent = open ? "✕" : "☰";
    });

    navMobile.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        navMobile.classList.remove("open");
        menuToggle.setAttribute("aria-expanded", "false");
        menuToggle.textContent = "☰";
      });
    });
  }

  if (copyBtn && installCmd) {
    copyBtn.addEventListener("click", async () => {
      const text = installCmd.textContent.trim();
      try {
        await navigator.clipboard.writeText(text);
        const original = copyBtn.textContent;
        copyBtn.textContent = "Copied!";
        setTimeout(() => {
          copyBtn.textContent = original;
        }, 1800);
      } catch {
        copyBtn.textContent = "Copy failed";
      }
    });
  }

  const revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealEls.length) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -30px 0px" }
    );
    revealEls.forEach((el) => observer.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add("visible"));
  }

  initRoutingDiagram(document.getElementById("routing-diagram"));
})();

function initRoutingDiagram(root) {
  if (!root) return;

  const canvas = root.querySelector(".routing-canvas");
  const svg = root.querySelector(".routing-edges");
  const nodes = root.querySelectorAll(".routing-node");
  if (!canvas || !svg || !nodes.length) return;

  const connections = [
    ["ask", "route"],
    ["route", "skills"],
    ["route", "llm"],
    ["skills", "output"],
    ["llm", "output"],
  ];

  const edgeEls = connections.map(([from, to]) => {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.classList.add("routing-edge");
    line.dataset.from = from;
    line.dataset.to = to;
    line.setAttribute("marker-end", "url(#routing-arrow)");
    svg.appendChild(line);
    return line;
  });

  function nodeCenter(node) {
    const canvasRect = canvas.getBoundingClientRect();
    const nodeRect = node.getBoundingClientRect();
    return {
      x: nodeRect.left + nodeRect.width / 2 - canvasRect.left,
      y: nodeRect.top + nodeRect.height / 2 - canvasRect.top,
    };
  }

  function drawEdges() {
    const { width, height } = canvas.getBoundingClientRect();
    if (!width || !height) return;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

    connections.forEach(([from, to], index) => {
      const fromNode = root.querySelector(`[data-node="${from}"]`);
      const toNode = root.querySelector(`[data-node="${to}"]`);
      const edge = edgeEls[index];
      if (!fromNode || !toNode || !edge) return;
      const start = nodeCenter(fromNode);
      const end = nodeCenter(toNode);
      edge.setAttribute("d", `M ${start.x} ${start.y} L ${end.x} ${end.y}`);
    });
  }

  function clearHighlight() {
    nodes.forEach((node) => node.classList.remove("active"));
    edgeEls.forEach((edge) => edge.classList.remove("highlight"));
  }

  nodes.forEach((node) => {
    function highlightNode() {
      const id = node.dataset.node;
      if (!id) return;
      clearHighlight();
      node.classList.add("active");
      edgeEls.forEach((edge) => {
        if (edge.dataset.from === id || edge.dataset.to === id) {
          edge.classList.add("highlight");
        }
      });
    }

    node.addEventListener("mouseenter", highlightNode);
    node.addEventListener("mouseleave", clearHighlight);
    node.addEventListener("focus", highlightNode);
    node.addEventListener("blur", clearHighlight);
  });

  drawEdges();
  window.addEventListener("resize", drawEdges);
  if ("ResizeObserver" in window) {
    new ResizeObserver(drawEdges).observe(canvas);
  }
}
