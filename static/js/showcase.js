(() => {
const galleryCards = document.querySelectorAll("[data-gallery-card]");
const previewModal = document.querySelector("[data-preview-modal]");
const previewClose = document.querySelector("[data-preview-close]");
const previewImage = document.querySelector("[data-preview-image]");
const previewTitle = document.querySelector("[data-preview-title]");
const previewDate = document.querySelector("[data-preview-date]");
const previewLink = document.querySelector("[data-preview-link]");
const csrfMeta = document.querySelector('meta[name="csrf-token"]');
const motionQuery = window.matchMedia("(prefers-reduced-motion: no-preference)");
let pendingHeartButton = null;
const viewerStates = new WeakMap();

if (galleryCards.length) {
    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-visible");
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.12 }
    );

    galleryCards.forEach((card) => observer.observe(card));
}

function closePreview() {
    if (!previewModal) {
        return;
    }

    previewModal.classList.add("is-hidden");
    document.body.style.overflow = "";
}

function openPreview(card) {
    if (!card || !previewModal) {
        return;
    }

    previewTitle.textContent = card.dataset.title || "Untitled";
    previewDate.textContent = card.dataset.date || "";
    previewLink.href = card.dataset.detailUrl;

    if (card.dataset.image) {
        previewImage.src = card.dataset.image;
        previewImage.alt = card.dataset.title || "Sketch preview";
        previewImage.parentElement.hidden = false;
    } else {
        previewImage.removeAttribute("src");
        previewImage.alt = "";
        previewImage.parentElement.hidden = true;
    }

    previewModal.classList.remove("is-hidden");
    document.body.style.overflow = "hidden";
}

function tiltCard(card, event) {
    const rect = card.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width - 0.5) * 7;
    const y = ((event.clientY - rect.top) / rect.height - 0.5) * -5;

    card.style.setProperty("--tilt-x", `${x.toFixed(2)}deg`);
    card.style.setProperty("--tilt-y", `${y.toFixed(2)}deg`);
}

function resetTilt(card) {
    card.style.setProperty("--tilt-x", "0deg");
    card.style.setProperty("--tilt-y", "0deg");
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

function updateHeartButtons(url, hearted, heartCount) {
    document.querySelectorAll(`[data-heart-url="${url}"]`).forEach((button) => {
        button.classList.toggle("is-hearted", hearted);
        button.setAttribute("aria-pressed", String(hearted));
        const count = button.querySelector("[data-heart-count]");
        if (count) {
            count.textContent = String(heartCount);
        }
        const icon = button.querySelector("[data-heart-icon]");
        if (icon) {
            icon.textContent = hearted ? "\u2665" : "\u2661";
        }
    });
}

function unlockHeartButtons(url) {
    document.querySelectorAll(`[data-heart-url="${url}"]`).forEach((button) => {
        button.removeAttribute("data-heart-login-url");
    });
}

function openHeartLoginModal(button, loginUrl) {
    pendingHeartButton = button;

    if (window.masdrawOpenAuthModal) {
        window.masdrawOpenAuthModal(loginUrl, button);
        return;
    }

    button.classList.add("has-error");
    window.setTimeout(() => button.classList.remove("has-error"), 1400);
}

function showHeartError(button, message) {
    if (message) {
        button.title = message;
    }
    button.classList.add("has-error");
    window.setTimeout(() => button.classList.remove("has-error"), 1600);
}

async function toggleHeart(button) {
    const loginUrl = button.dataset.heartLoginUrl;
    if (loginUrl) {
        openHeartLoginModal(button, loginUrl);
        return;
    }

    const heartUrl = button.dataset.heartUrl;
    if (!heartUrl || button.disabled) {
        return;
    }

    button.disabled = true;

    try {
        const response = await fetch(heartUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Accept": "application/json",
                "X-CSRFToken": getCsrfToken(),
                "X-Requested-With": "XMLHttpRequest",
            },
        });

        if (response.redirected) {
            openHeartLoginModal(button, response.url);
            return;
        }

        const data = await response.json();
        if (response.ok && data.success) {
            updateHeartButtons(heartUrl, data.hearted, data.heart_count);
        } else {
            showHeartError(button, data.error || "Heart action failed. Please try again.");
        }
    } catch (error) {
        showHeartError(button, "Heart action failed. Please try again.");
    } finally {
        button.disabled = false;
    }
}

function getViewerState(viewer) {
    if (!viewerStates.has(viewer)) {
        viewerStates.set(viewer, {
            scale: 1,
            panX: 0,
            panY: 0,
            isPanning: false,
            lastX: 0,
            lastY: 0,
        });
    }
    return viewerStates.get(viewer);
}

function applyViewerTransform(viewer) {
    const state = getViewerState(viewer);
    viewer.style.setProperty("--viewer-scale", state.scale.toFixed(2));
    viewer.style.setProperty("--viewer-pan-x", `${Math.round(state.panX)}px`);
    viewer.style.setProperty("--viewer-pan-y", `${Math.round(state.panY)}px`);

    const scaleLabel = viewer.querySelector("[data-viewer-scale]");
    if (scaleLabel) {
        scaleLabel.textContent = `${Math.round(state.scale * 100)}%`;
    }
}

function updateViewerScale(viewer, nextScale) {
    const state = getViewerState(viewer);
    state.scale = Math.min(3, Math.max(0.5, nextScale));
    if (state.scale <= 1) {
        state.panX = 0;
        state.panY = 0;
    }
    applyViewerTransform(viewer);
}

function resetViewer(viewer) {
    const state = getViewerState(viewer);
    state.scale = 1;
    state.panX = 0;
    state.panY = 0;
    state.isPanning = false;
    viewer.classList.remove("is-panning");
    applyViewerTransform(viewer);
}

function startViewerPan(viewer, canvas, event) {
    const state = getViewerState(viewer);
    if (state.scale <= 1 || event.button !== 0) {
        return;
    }

    event.preventDefault();
    state.isPanning = true;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    viewer.classList.add("is-panning");

    if (canvas.setPointerCapture) {
        canvas.setPointerCapture(event.pointerId);
    }
}

function moveViewerPan(viewer, event) {
    const state = getViewerState(viewer);
    if (!state.isPanning) {
        return;
    }

    event.preventDefault();
    state.panX += event.clientX - state.lastX;
    state.panY += event.clientY - state.lastY;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    applyViewerTransform(viewer);
}

function stopViewerPan(viewer) {
    const state = getViewerState(viewer);
    state.isPanning = false;
    viewer.classList.remove("is-panning");
}

function downloadViewerImage(viewer, button) {
    const image = viewer.querySelector("[data-viewer-image]");
    if (!image || !image.src) {
        return;
    }

    const link = document.createElement("a");
    link.href = image.src;
    link.download = button.dataset.downloadName || "masdraw-sketch.png";
    document.body.appendChild(link);
    link.click();
    link.remove();
}

async function toggleViewerFullscreen(viewer) {
    if (!document.fullscreenElement) {
        if (viewer.requestFullscreen) {
            await viewer.requestFullscreen();
        }
        return;
    }

    if (document.exitFullscreen) {
        await document.exitFullscreen();
    }
}

function updateFullscreenButtons() {
    document.querySelectorAll("[data-sketch-viewer]").forEach((viewer) => {
        const button = viewer.querySelector("[data-viewer-fullscreen]");
        if (!button) {
            return;
        }
        button.textContent = document.fullscreenElement === viewer ? "Exit Full Screen" : "Full Screen";
    });
}

function initializeSketchViewers() {
    document.querySelectorAll("[data-sketch-viewer]").forEach((viewer) => {
        const zoomOut = viewer.querySelector("[data-viewer-zoom-out]");
        const zoomIn = viewer.querySelector("[data-viewer-zoom-in]");
        const reset = viewer.querySelector("[data-viewer-reset]");
        const fullscreen = viewer.querySelector("[data-viewer-fullscreen]");
        const download = viewer.querySelector("[data-viewer-download]");

        updateViewerScale(viewer, 1);

        if (zoomOut) {
            zoomOut.addEventListener("click", () => {
                updateViewerScale(viewer, getViewerState(viewer).scale - 0.25);
            });
        }

        if (zoomIn) {
            zoomIn.addEventListener("click", () => {
                updateViewerScale(viewer, getViewerState(viewer).scale + 0.25);
            });
        }

        if (reset) {
            reset.addEventListener("click", () => {
                resetViewer(viewer);
            });
        }

        if (fullscreen) {
            fullscreen.addEventListener("click", () => {
                toggleViewerFullscreen(viewer).catch(() => {
                    fullscreen.classList.add("has-error");
                    window.setTimeout(() => fullscreen.classList.remove("has-error"), 1400);
                });
            });
        }

        if (download) {
            download.addEventListener("click", () => {
                downloadViewerImage(viewer, download);
            });
        }

        const canvas = viewer.querySelector("[data-viewer-canvas]");
        if (canvas) {
            canvas.addEventListener("pointerdown", (event) => {
                startViewerPan(viewer, canvas, event);
            });
            canvas.addEventListener("pointermove", (event) => {
                moveViewerPan(viewer, event);
            });
            canvas.addEventListener("pointerup", () => {
                stopViewerPan(viewer);
            });
            canvas.addEventListener("pointercancel", () => {
                stopViewerPan(viewer);
            });
            canvas.addEventListener("pointerleave", () => {
                stopViewerPan(viewer);
            });
        }
    });
}

if (motionQuery.matches) {
    document.querySelectorAll(".gallery-card").forEach((card) => {
        card.addEventListener("pointermove", (event) => tiltCard(card, event));
        card.addEventListener("pointerleave", () => resetTilt(card));
    });
}

if (previewModal) {
    document.querySelectorAll("[data-quick-view]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            openPreview(button.closest("[data-gallery-card]"));
        });
    });

    previewClose.addEventListener("click", closePreview);

    previewModal.addEventListener("click", (event) => {
        if (event.target === previewModal) {
            closePreview();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !previewModal.classList.contains("is-hidden")) {
            closePreview();
        }
    });
}

initializeSketchViewers();
document.addEventListener("fullscreenchange", updateFullscreenButtons);

document.querySelectorAll("[data-heart-button]").forEach((button) => {
    button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleHeart(button);
    });
});

document.addEventListener("masdraw:auth-success", () => {
    if (!pendingHeartButton) {
        return;
    }

    const button = pendingHeartButton;
    pendingHeartButton = null;
    unlockHeartButtons(button.dataset.heartUrl);
    toggleHeart(button);
});

document.addEventListener("masdraw:auth-modal-close", () => {
    pendingHeartButton = null;
});
})();
