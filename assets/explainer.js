(() => {
  "use strict";

  const root = document.documentElement;
  const revealItems = [...document.querySelectorAll(".reveal")];
  const storySections = [...document.querySelectorAll(".story-section[id]")];
  const storyLinks = [...document.querySelectorAll(".story-nav a")];
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  root.classList.add("js");

  const showAll = () => {
    revealItems.forEach((item) => item.classList.add("is-visible"));
  };

  if (reducedMotion.matches || !("IntersectionObserver" in window)) {
    showAll();
  } else {
    const revealObserver = new IntersectionObserver(
      (entries, observer) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      {
        threshold: 0.16,
        rootMargin: "0px 0px -8% 0px",
      },
    );

    revealItems.forEach((item) => revealObserver.observe(item));
  }

  if ("IntersectionObserver" in window && storySections.length) {
    const sectionObserver = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((first, second) => second.intersectionRatio - first.intersectionRatio);

        if (!visible.length) {
          return;
        }

        const currentId = visible[0].target.id;
        storyLinks.forEach((link) => {
          const isCurrent = link.getAttribute("href") === `#${currentId}`;
          link.classList.toggle("is-current", isCurrent);
          if (isCurrent) {
            link.setAttribute("aria-current", "location");
          } else {
            link.removeAttribute("aria-current");
          }
        });
      },
      {
        threshold: [0.2, 0.45, 0.7],
        rootMargin: "-18% 0px -52% 0px",
      },
    );

    storySections.forEach((section) => sectionObserver.observe(section));
  }

  const handleMotionPreference = (event) => {
    if (event.matches) {
      showAll();
    }
  };

  if (typeof reducedMotion.addEventListener === "function") {
    reducedMotion.addEventListener("change", handleMotionPreference);
  } else if (typeof reducedMotion.addListener === "function") {
    reducedMotion.addListener(handleMotionPreference);
  }
})();
