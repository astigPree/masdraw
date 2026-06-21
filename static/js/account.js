const authModal = document.querySelector("[data-auth-modal-shell]");
const authDialog = document.querySelector("[data-auth-modal-dialog]");
const authModalTitle = document.querySelector("[data-auth-modal-title]");
const authModalStatus = document.querySelector("[data-auth-modal-status]");
const authModalContent = document.querySelector("[data-auth-modal-content]");
const authNav = document.querySelector("[data-auth-nav]");
const authToast = document.querySelector("[data-auth-toast]");
const csrfMeta = document.querySelector('meta[name="csrf-token"]');

let lastFocusedElement = null;
let authToastTimer = null;

function dispatchAuthSuccess(data) {
    document.dispatchEvent(new CustomEvent("masdraw:auth-success", { detail: data || {} }));
}

function dispatchAuthModalClose() {
    document.dispatchEvent(new CustomEvent("masdraw:auth-modal-close"));
}

function getCsrfToken() {
    if (csrfMeta && csrfMeta.content) {
        return csrfMeta.content;
    }

    const csrfCookie = document.cookie
        .split("; ")
        .find((cookie) => cookie.startsWith("csrftoken="));
    return csrfCookie ? decodeURIComponent(csrfCookie.split("=")[1]) : "";
}

function updateCsrfToken(token) {
    if (!token || !csrfMeta) {
        return;
    }
    csrfMeta.content = token;
}

function authHeaders() {
    return {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": getCsrfToken(),
    };
}

function showToast(message) {
    if (!authToast || !message) {
        return;
    }

    window.clearTimeout(authToastTimer);
    authToast.textContent = message;
    authToast.setAttribute("aria-hidden", "false");
    authToast.classList.add("is-visible");

    authToastTimer = window.setTimeout(() => {
        authToast.classList.remove("is-visible");
        authToast.setAttribute("aria-hidden", "true");
    }, 3200);
}

function setModalStatus(message) {
    if (!authModalStatus) {
        return;
    }
    authModalStatus.textContent = message || "";
    authModalStatus.classList.toggle("is-visible", Boolean(message));
}

function focusFirstAuthField() {
    if (!authModalContent) {
        return;
    }

    const firstField = authModalContent.querySelector("input:not([type='hidden']), button, a");
    if (firstField) {
        firstField.focus();
    }
}

function showAuthModal() {
    if (!authModal || !authDialog) {
        return;
    }

    authModal.classList.add("is-open");
    authModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("auth-modal-open");
    authDialog.focus();
}

function closeAuthModal() {
    if (!authModal) {
        return;
    }

    authModal.classList.remove("is-open");
    authModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("auth-modal-open");
    setModalStatus("");

    if (lastFocusedElement) {
        lastFocusedElement.focus();
    }
    dispatchAuthModalClose();
}

function renderAuthModal(title, html, statusMessage) {
    if (!authModalTitle || !authModalContent) {
        return;
    }

    authModalTitle.textContent = title || "Account";
    authModalContent.innerHTML = html || "";
    setModalStatus(statusMessage || "");
    showAuthModal();
    focusFirstAuthField();
}

function setSubmitState(form, isSubmitting) {
    const submitButton = form.querySelector("button[type='submit']");
    if (!submitButton) {
        return;
    }
    submitButton.disabled = isSubmitting;
    submitButton.classList.toggle("is-loading", isSubmitting);
}

function renderAuthenticatedNav(data) {
    if (!authNav) {
        return;
    }

    authNav.innerHTML = "";

    const drawingsLink = document.createElement("a");
    drawingsLink.href = data.my_drawings_url || "/account/drawings/";
    drawingsLink.textContent = "My Drawings";

    const accountLink = document.createElement("a");
    accountLink.href = data.account_url || "/account/";
    accountLink.textContent = "My Account";

    const logoutForm = document.createElement("form");
    logoutForm.method = "post";
    logoutForm.action = data.logout_url || "/logout/";
    logoutForm.setAttribute("data-auth-logout", "");

    const csrfInput = document.createElement("input");
    csrfInput.type = "hidden";
    csrfInput.name = "csrfmiddlewaretoken";
    csrfInput.value = getCsrfToken();

    const logoutButton = document.createElement("button");
    logoutButton.type = "submit";
    logoutButton.textContent = "Logout";

    logoutForm.append(csrfInput, logoutButton);
    authNav.append(drawingsLink, accountLink, logoutForm);
}

function renderAnonymousNav(data) {
    if (!authNav) {
        return;
    }

    authNav.innerHTML = "";

    const loginLink = document.createElement("a");
    loginLink.href = data.login_url || "/login/";
    loginLink.textContent = "Login";
    loginLink.setAttribute("data-auth-modal", "login");

    const registerLink = document.createElement("a");
    registerLink.href = data.register_url || "/register/";
    registerLink.textContent = "Register";
    registerLink.setAttribute("data-auth-modal", "register");

    authNav.append(loginLink, registerLink);
}

async function parseJsonResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
        throw new Error("Expected a JSON response.");
    }
    return response.json();
}

async function openAuthModal(url, trigger) {
    if (!authModal || !authModalContent) {
        return;
    }

    lastFocusedElement = trigger || document.activeElement;
    renderAuthModal("Account", '<div class="auth-modal-loading">Loading...</div>', "");

    try {
        const response = await fetch(url, {
            method: "GET",
            credentials: "same-origin",
            headers: authHeaders(),
        });
        const data = await parseJsonResponse(response);

        if (data.csrf_token) {
            updateCsrfToken(data.csrf_token);
        }
        if (data.authenticated) {
            renderAuthenticatedNav(data);
            dispatchAuthSuccess(data);
            closeAuthModal();
            showToast(data.message || "You are logged in.");
            return;
        }

        renderAuthModal(data.title, data.html, trigger?.dataset.authPrompt || data.message);
    } catch (error) {
        setModalStatus("The account popup could not load. Try again.");
    }
}

async function submitAuthForm(form) {
    setSubmitState(form, true);
    setModalStatus("");

    try {
        const response = await fetch(form.action, {
            method: "POST",
            credentials: "same-origin",
            headers: authHeaders(),
            body: new FormData(form),
        });
        const data = await parseJsonResponse(response);

        if (data.csrf_token) {
            updateCsrfToken(data.csrf_token);
        }

        if (response.ok && data.ok && data.authenticated) {
            renderAuthenticatedNav(data);
            dispatchAuthSuccess(data);
            closeAuthModal();
            showToast(data.message || "You are logged in.");
            return;
        }

        renderAuthModal(data.title, data.html, data.message);
    } catch (error) {
        setModalStatus("The form could not be submitted. Try again.");
    } finally {
        setSubmitState(form, false);
    }
}

async function submitLogout(form) {
    try {
        const response = await fetch(form.action, {
            method: "POST",
            credentials: "same-origin",
            headers: authHeaders(),
            body: new FormData(form),
        });
        const data = await parseJsonResponse(response);

        if (data.csrf_token) {
            updateCsrfToken(data.csrf_token);
        }
        if (response.ok && data.ok && data.authenticated === false) {
            renderAnonymousNav(data);
            showToast(data.message || "You have been logged out.");
        }
    } catch (error) {
        showToast("Logout failed. Try again.");
    }
}

document.addEventListener("click", (event) => {
    const authTrigger = event.target.closest("[data-auth-modal]");
    if (authTrigger) {
        event.preventDefault();
        openAuthModal(authTrigger.href, authTrigger);
        return;
    }

    if (event.target.closest("[data-auth-modal-close]")) {
        event.preventDefault();
        closeAuthModal();
    }
});

document.addEventListener("submit", (event) => {
    const authForm = event.target.closest("[data-auth-form]");
    if (authForm) {
        event.preventDefault();
        submitAuthForm(authForm);
        return;
    }

    const logoutForm = event.target.closest("[data-auth-logout]");
    if (logoutForm) {
        if (window.location.pathname.startsWith("/account/")) {
            return;
        }
        event.preventDefault();
        submitLogout(logoutForm);
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && authModal && authModal.classList.contains("is-open")) {
        closeAuthModal();
    }
});

window.masdrawOpenAuthModal = openAuthModal;
