const navToggle = document.querySelector("[data-nav-toggle]");
const siteNav = document.querySelector("[data-site-nav]");
const pageLoader = document.querySelector("[data-page-loader]");

function showPageLoader() {
    if (!pageLoader) {
        return;
    }
    pageLoader.classList.add("is-active");
    pageLoader.setAttribute("aria-hidden", "false");
}

function shouldSkipLoaderForLink(link, event) {
    if (!link || event.defaultPrevented) {
        return true;
    }
    if (link.matches("[data-auth-modal]")) {
        return true;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return true;
    }
    if (link.target && link.target !== "_self") {
        return true;
    }
    if (link.hasAttribute("download")) {
        return true;
    }

    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) {
        return true;
    }
    return url.pathname === window.location.pathname && url.search === window.location.search && url.hash;
}

if (navToggle && siteNav) {
    navToggle.addEventListener("click", () => {
        const isOpen = navToggle.getAttribute("aria-expanded") === "true";
        navToggle.setAttribute("aria-expanded", String(!isOpen));
        siteNav.classList.toggle("is-open", !isOpen);
        document.body.classList.toggle("nav-open", !isOpen);
    });

    siteNav.addEventListener("click", (event) => {
        const target = event.target;
        if (target.closest("a") || target.closest("button")) {
            navToggle.setAttribute("aria-expanded", "false");
            siteNav.classList.remove("is-open");
            document.body.classList.remove("nav-open");
        }
    });
}

document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (shouldSkipLoaderForLink(link, event)) {
        return;
    }
    showPageLoader();
});

document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.matches("[data-auth-form], [data-auth-logout]")) {
        return;
    }
    if (form.matches("form")) {
        showPageLoader();
    }
});

window.addEventListener("pageshow", () => {
    if (!pageLoader) {
        return;
    }
    pageLoader.classList.remove("is-active");
    pageLoader.setAttribute("aria-hidden", "true");
});
