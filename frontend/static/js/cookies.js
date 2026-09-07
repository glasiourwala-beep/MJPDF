(function () {
  const KEY = "mjpdf_cookie_consent_v1";

  function getConsent() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  function setConsent(value) {
    try {
      localStorage.setItem(KEY, JSON.stringify(value));
    } catch (_) {}
  }

  function lockPage(lock) {
    document.documentElement.classList.toggle("cookie-lock", !!lock);
    document.body.classList.toggle("cookie-lock", !!lock);
  }

  function hideBanner() {
    const el = document.getElementById("cookie-banner");
    const overlay = document.getElementById("cookie-overlay");
    if (el) {
      el.classList.add("hidden");
      el.setAttribute("aria-hidden", "true");
    }
    if (overlay) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
    }
    lockPage(false);
  }

  function showBanner() {
    const el = document.getElementById("cookie-banner");
    const overlay = document.getElementById("cookie-overlay");
    if (overlay) {
      overlay.classList.remove("hidden");
      overlay.setAttribute("aria-hidden", "false");
    }
    if (el) {
      el.classList.remove("hidden");
      el.setAttribute("aria-hidden", "false");
    }
    lockPage(true);
  }

  function openSettings(open) {
    const panel = document.getElementById("cookie-settings");
    if (!panel) return;
    panel.classList.toggle("hidden", !open);
  }

  function bind() {
    const existing = getConsent();
    if (!existing || !existing.choice) {
      showBanner();
    } else {
      hideBanner();
    }

    document.getElementById("cookie-accept")?.addEventListener("click", function () {
      setConsent({ essential: true, analytics: false, ts: Date.now(), choice: "accept" });
      hideBanner();
    });
    document.getElementById("cookie-reject")?.addEventListener("click", function () {
      setConsent({ essential: true, analytics: false, ts: Date.now(), choice: "reject" });
      hideBanner();
    });
    document.getElementById("cookie-settings-btn")?.addEventListener("click", function () {
      openSettings(true);
    });
    document.getElementById("cookie-save")?.addEventListener("click", function () {
      var analytics = !!document.getElementById("cookie-analytics")?.checked;
      setConsent({ essential: true, analytics: analytics, ts: Date.now(), choice: "custom" });
      hideBanner();
    });
    document.getElementById("cookie-reopen")?.addEventListener("click", function (e) {
      e.preventDefault();
      openSettings(true);
      showBanner();
    });
    document.getElementById("cookie-overlay")?.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  window.MJPDFCookies = {
    getConsent: getConsent,
    setConsent: setConsent,
    showBanner: showBanner,
    clearConsent: function () {
      try { localStorage.removeItem(KEY); } catch (_) {}
      showBanner();
    }
  };
})();
