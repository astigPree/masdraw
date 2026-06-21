const shell = document.querySelector(".draw-shell");
const canvas = document.getElementById("drawingCanvas");

if (shell && canvas) {
    const ctx = canvas.getContext("2d");
    const canvasViewport = document.querySelector("[data-canvas-viewport]");
    const canvasSizeInput = document.querySelector("[data-canvas-size]");
    const saveUrl = shell.dataset.saveUrl;
    const publishUrl = shell.dataset.publishUrl;
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

    const statusEl = document.querySelector("[data-save-status]");
    const titleInput = document.querySelector("[data-title-input]");
    const brushSizeInput = document.querySelector("[data-brush-size]");
    const brushColorInput = document.querySelector("[data-brush-color]");
    const backgroundColorInput = document.querySelector("[data-background-color]");
    const colorSwatches = document.querySelectorAll("[data-color-swatch]");
    const sizeValue = document.querySelector("[data-size-value]");
    const toolButtons = document.querySelectorAll("[data-tool]");
    const undoButton = document.querySelector("[data-undo-button]");
    const clearButton = document.querySelector("[data-clear-button]");
    const fillButton = document.querySelector("[data-fill-button]");
    const saveButton = document.querySelector("[data-save-button]");
    const moreToggle = document.querySelector("[data-more-toggle]");
    const morePanel = document.querySelector("[data-more-panel]");
    const symmetryToggle = document.querySelector("[data-symmetry-toggle]");
    const zoomInButton = document.querySelector("[data-zoom-in]");
    const zoomOutButton = document.querySelector("[data-zoom-out]");
    const zoomResetButton = document.querySelector("[data-zoom-reset]");
    const panButton = document.querySelector("[data-pan-canvas]");
    const fullscreenButton = document.querySelector("[data-fullscreen-canvas]");
    const exitFullscreenButton = document.querySelector("[data-exit-fullscreen]");
    const publishButton = document.querySelector("[data-publish-button]");
    const publishMessage = document.querySelector("[data-publish-message]");
    const recoveryModal = document.querySelector("[data-recovery-modal]");
    const clearConfirmModal = document.querySelector("[data-clear-confirm-modal]");
    const cancelClearButton = document.querySelector("[data-cancel-clear]");
    const confirmClearButton = document.querySelector("[data-confirm-clear]");
    const textModal = document.querySelector("[data-text-modal]");
    const textInput = document.querySelector("[data-text-input]");
    const cancelTextButton = document.querySelector("[data-cancel-text]");
    const confirmTextButton = document.querySelector("[data-confirm-text]");
    const closeModalButton = document.querySelector("[data-close-modal]");
    const copyButtons = document.querySelectorAll("[data-copy-key]");
    const downloadButton = document.querySelector("[data-download-key]");
    const passKey = document.getElementById("passKey");

    let elements = [];
    let currentElement = null;
    let pendingTextPoint = null;
    let movingTextElement = null;
    let moveTextOffset = { x: 0, y: 0 };
    let activeTool = "brush";
    let backgroundColor = "#ffffff";
    let isDrawing = false;
    let isDirty = false;
    let symmetryEnabled = false;
    let saveTimer = null;
    let redrawPending = false;
    let canvasSize = { width: 1200, height: 820 };
    let canvasZoom = 1;
    let zoomMode = "fit";
    let isPanMode = false;
    let activePan = null;

    const shapeTools = ["line", "rect", "circle"];
    const minZoom = 0.2;
    const maxZoom = 3;
    const zoomStep = 0.15;

    const initialDataEl = document.getElementById("initialDrawingData");
    if (initialDataEl) {
        const initialData = JSON.parse(initialDataEl.textContent || "{}");
        elements = Array.isArray(initialData.elements) ? initialData.elements : [];
        if (!elements.length && Array.isArray(initialData.strokes)) {
            elements = initialData.strokes.map((stroke) => ({
                ...stroke,
                type: stroke.type || stroke.tool || "brush",
            }));
        }
        backgroundColor = initialData.backgroundColor || "#ffffff";
        if (
            initialData.canvasSize &&
            Number(initialData.canvasSize.width) > 0 &&
            Number(initialData.canvasSize.height) > 0
        ) {
            canvasSize = {
                width: Number(initialData.canvasSize.width),
                height: Number(initialData.canvasSize.height),
            };
        }
    }

    function canvasRect() {
        return canvas.getBoundingClientRect();
    }

    function clampZoom(value) {
        return Math.min(maxZoom, Math.max(minZoom, value));
    }

    function canvasSizeValue(size) {
        return `${size.width}x${size.height}`;
    }

    function parseCanvasSize(value) {
        const [width, height] = value.split("x").map((part) => Number(part));
        if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
            return { width: 1200, height: 820 };
        }
        return { width, height };
    }

    function computeFitZoom() {
        const viewportRect = canvasViewport.getBoundingClientRect();
        const availableWidth = Math.max(260, viewportRect.width - 24);
        const availableHeight = Math.max(260, viewportRect.height - 24);
        const widthZoom = availableWidth / canvasSize.width;

        if (document.fullscreenElement === canvasViewport) {
            return clampZoom(Math.min(widthZoom, availableHeight / canvasSize.height));
        }

        return clampZoom(widthZoom);
    }

    function updateZoomLabel() {
        zoomResetButton.textContent = `${Math.round(canvasZoom * 100)}%`;
        zoomResetButton.title = zoomMode === "fit" ? "Canvas is fit to screen" : "Reset zoom to fit";
    }

    function syncCanvasSurface() {
        canvas.width = canvasSize.width;
        canvas.height = canvasSize.height;
        canvas.style.width = `${Math.round(canvasSize.width * canvasZoom)}px`;
        canvas.style.height = `${Math.round(canvasSize.height * canvasZoom)}px`;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        updateZoomLabel();
        redraw();
    }

    function setCanvasZoom(value, mode = "manual") {
        canvasZoom = clampZoom(value);
        zoomMode = mode;
        syncCanvasSurface();
    }

    function fitCanvas() {
        setCanvasZoom(computeFitZoom(), "fit");
    }

    function applyCanvasSize(nextSize, shouldMarkDirty = false) {
        canvasSize = nextSize;
        canvasSizeInput.value = canvasSizeValue(canvasSize);

        if (zoomMode === "fit") {
            fitCanvas();
        } else {
            syncCanvasSurface();
        }

        if (shouldMarkDirty) {
            markDirty();
        }
    }

    function setStatus(label, state) {
        statusEl.textContent = label;
        statusEl.classList.remove("is-saving", "is-unsaved");
        if (state) {
            statusEl.classList.add(state);
        }
    }

    function setActiveTool(tool) {
        activeTool = tool;
        toolButtons.forEach((button) => {
            const isActive = button.dataset.tool === tool;
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-pressed", String(isActive));
        });
    }

    function setPanMode(isActive) {
        isPanMode = isActive;
        activePan = null;
        panButton.classList.toggle("is-active", isPanMode);
        panButton.setAttribute("aria-pressed", String(isPanMode));
        canvasViewport.classList.toggle("is-pan-mode", isPanMode);
        canvasViewport.classList.remove("is-panning");
    }

    function syncActiveSwatch(color) {
        colorSwatches.forEach((swatch) => {
            swatch.classList.toggle(
                "is-active",
                swatch.dataset.colorSwatch.toLowerCase() === color.toLowerCase()
            );
        });
    }

    function setBrushColor(color) {
        brushColorInput.value = color;
        document.documentElement.style.setProperty("--active-color", color);
        syncActiveSwatch(color);
    }

    function getNormalizedTitle() {
        return titleInput.value.trim();
    }

    function pointFromEvent(event) {
        const rect = canvasRect();
        return {
            x: (event.clientX - rect.left) * (canvasSize.width / rect.width),
            y: (event.clientY - rect.top) * (canvasSize.height / rect.height),
        };
    }

    function startCanvasPan(event) {
        if (event.button !== 0 && event.pointerType !== "touch") {
            return;
        }

        event.preventDefault();
        canvas.setPointerCapture(event.pointerId);
        activePan = {
            pointerId: event.pointerId,
            x: event.clientX,
            y: event.clientY,
            scrollLeft: canvasViewport.scrollLeft,
            scrollTop: canvasViewport.scrollTop,
        };
        canvasViewport.classList.add("is-panning");
    }

    function moveCanvasPan(event) {
        if (!activePan || activePan.pointerId !== event.pointerId) {
            return;
        }

        event.preventDefault();
        canvasViewport.scrollLeft = activePan.scrollLeft - (event.clientX - activePan.x);
        canvasViewport.scrollTop = activePan.scrollTop - (event.clientY - activePan.y);
    }

    function finishCanvasPan(event) {
        if (!activePan || (event && activePan.pointerId !== event.pointerId)) {
            return;
        }

        if (event) {
            event.preventDefault();
            if (canvas.hasPointerCapture(event.pointerId)) {
                canvas.releasePointerCapture(event.pointerId);
            }
        }

        activePan = null;
        canvasViewport.classList.remove("is-panning");
    }

    function mirrorPoint(point) {
        return {
            x: canvasSize.width - point.x,
            y: point.y,
        };
    }

    function mirroredElement(element) {
        const mirrored = { ...element };
        if (element.points) {
            mirrored.points = element.points.map(mirrorPoint);
        }
        if (element.x !== undefined) {
            mirrored.x = canvasSize.width - element.x;
        }
        return mirrored;
    }

    function markDirty() {
        isDirty = true;
        setStatus("Unsaved changes", "is-unsaved");
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(saveDrawing, 3500);
    }

    function drawFreehand(element) {
        if (!element.points || !element.points.length) {
            return;
        }

        ctx.save();
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.strokeStyle = element.type === "eraser" ? backgroundColor : element.color;
        ctx.lineWidth = element.type === "highlighter" ? element.size * 1.8 : element.size;
        ctx.globalAlpha = element.type === "highlighter" ? 0.35 : 1;

        ctx.beginPath();
        ctx.moveTo(element.points[0].x, element.points[0].y);

        for (let index = 1; index < element.points.length; index += 1) {
            const point = element.points[index];
            const previous = element.points[index - 1];
            const midX = (previous.x + point.x) / 2;
            const midY = (previous.y + point.y) / 2;
            ctx.quadraticCurveTo(previous.x, previous.y, midX, midY);
        }

        ctx.stroke();
        ctx.restore();
    }

    function drawShape(element) {
        if (!element.points || element.points.length < 2) {
            return;
        }

        const start = element.points[0];
        const end = element.points[element.points.length - 1];
        const width = end.x - start.x;
        const height = end.y - start.y;

        ctx.save();
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.strokeStyle = element.color;
        ctx.lineWidth = element.size;
        ctx.beginPath();

        if (element.type === "line") {
            ctx.moveTo(start.x, start.y);
            ctx.lineTo(end.x, end.y);
        }

        if (element.type === "rect") {
            ctx.rect(start.x, start.y, width, height);
        }

        if (element.type === "circle") {
            const radius = Math.sqrt(width * width + height * height);
            ctx.arc(start.x, start.y, radius, 0, Math.PI * 2);
        }

        ctx.stroke();
        ctx.restore();
    }

    function drawText(element) {
        ctx.save();
        ctx.fillStyle = element.color;
        ctx.font = `${element.fontSize}px Inter, Arial, sans-serif`;
        ctx.textBaseline = "top";
        ctx.fillText(element.text, element.x, element.y);
        ctx.restore();
    }

    function textBounds(element) {
        ctx.save();
        ctx.font = `${element.fontSize}px Inter, Arial, sans-serif`;
        const width = ctx.measureText(element.text).width;
        ctx.restore();
        return {
            x: element.x,
            y: element.y,
            width,
            height: element.fontSize * 1.25,
        };
    }

    function findTextAtPoint(point) {
        for (let index = elements.length - 1; index >= 0; index -= 1) {
            const element = elements[index];
            if (element.type !== "text") {
                continue;
            }
            const bounds = textBounds(element);
            if (
                point.x >= bounds.x &&
                point.x <= bounds.x + bounds.width &&
                point.y >= bounds.y &&
                point.y <= bounds.y + bounds.height
            ) {
                return element;
            }
        }
        return null;
    }

    function drawElement(element) {
        if (["line", "rect", "circle"].includes(element.type)) {
            drawShape(element);
            return;
        }
        if (element.type === "text") {
            drawText(element);
            return;
        }
        drawFreehand(element);
    }

    function redrawNow() {
        ctx.clearRect(0, 0, canvasSize.width, canvasSize.height);
        ctx.fillStyle = backgroundColor;
        ctx.fillRect(0, 0, canvasSize.width, canvasSize.height);

        elements.forEach(drawElement);

        if (currentElement) {
            drawElement(currentElement);
            if (symmetryEnabled && currentElement.type !== "fill") {
                drawElement(mirroredElement(currentElement));
            }
        }
    }

    function redraw() {
        if (redrawPending) {
            return;
        }
        redrawPending = true;
        requestAnimationFrame(() => {
            redrawPending = false;
            redrawNow();
        });
    }

    function createElement(point) {
        return {
            groupId: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
            type: activeTool,
            color: activeTool === "eraser" ? backgroundColor : brushColorInput.value,
            size: activeTool === "highlighter" ? Number(brushSizeInput.value) + 8 : Number(brushSizeInput.value),
            points: [point],
        };
    }

    function openTextModal(point) {
        pendingTextPoint = point;
        textInput.value = "";
        textModal.classList.remove("is-hidden");
        window.setTimeout(() => textInput.focus(), 50);
    }

    function commitText() {
        const text = textInput.value.trim();
        if (!text || !pendingTextPoint) {
            textModal.classList.add("is-hidden");
            return;
        }

        const element = {
            groupId: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
            type: "text",
            text,
            x: pendingTextPoint.x,
            y: pendingTextPoint.y,
            color: brushColorInput.value,
            fontSize: Math.max(14, Number(brushSizeInput.value) * 2),
        };

        elements.push(element);
        if (symmetryEnabled) {
            elements.push(mirroredElement(element));
        }
        pendingTextPoint = null;
        textModal.classList.add("is-hidden");
        markDirty();
        redraw();
    }

    function startElement(event) {
        if (isPanMode) {
            startCanvasPan(event);
            return;
        }

        event.preventDefault();
        const point = pointFromEvent(event);

        if (activeTool === "fill") {
            backgroundColor = brushColorInput.value;
            backgroundColorInput.value = backgroundColor;
            document.documentElement.style.setProperty("--active-bg-color", backgroundColor);
            markDirty();
            redraw();
            return;
        }

        if (activeTool === "text") {
            openTextModal(point);
            return;
        }

        if (activeTool === "move-text") {
            movingTextElement = findTextAtPoint(point);
            if (movingTextElement) {
                canvas.setPointerCapture(event.pointerId);
                isDrawing = true;
                moveTextOffset = {
                    x: point.x - movingTextElement.x,
                    y: point.y - movingTextElement.y,
                };
            }
            return;
        }

        canvas.setPointerCapture(event.pointerId);
        isDrawing = true;
        currentElement = createElement(point);
        redraw();
    }

    function moveElement(event) {
        if (activePan) {
            moveCanvasPan(event);
            return;
        }

        if (!isDrawing) {
            return;
        }

        event.preventDefault();
        const point = pointFromEvent(event);

        if (activeTool === "move-text" && movingTextElement) {
            movingTextElement.x = point.x - moveTextOffset.x;
            movingTextElement.y = point.y - moveTextOffset.y;
            redraw();
            return;
        }

        if (!currentElement) {
            return;
        }

        if (shapeTools.includes(currentElement.type)) {
            currentElement.points = [currentElement.points[0], point];
        } else {
            currentElement.points.push(point);
        }

        redraw();
    }

    function finishElement(event) {
        if (activePan) {
            finishCanvasPan(event);
            return;
        }

        if (activeTool === "move-text" && movingTextElement) {
            movingTextElement = null;
            isDrawing = false;
            markDirty();
            redraw();
            return;
        }

        if (!currentElement) {
            return;
        }

        if (event) {
            event.preventDefault();
        }

        if (currentElement.points.length > 1) {
            elements.push(currentElement);
            if (symmetryEnabled) {
                elements.push(mirroredElement(currentElement));
            }
            markDirty();
        }

        currentElement = null;
        isDrawing = false;
        redraw();
    }

    function fillCanvas() {
        backgroundColor = brushColorInput.value;
        backgroundColorInput.value = backgroundColor;
        document.documentElement.style.setProperty("--active-bg-color", backgroundColor);
        markDirty();
        redraw();
    }

    function undoLast() {
        const removedElement = elements.pop();
        if (removedElement && removedElement.groupId) {
            const previousElement = elements[elements.length - 1];
            if (previousElement && previousElement.groupId === removedElement.groupId) {
                elements.pop();
            }
        }
        markDirty();
        redraw();
    }

    function clearCanvas() {
        elements = [];
        markDirty();
        redraw();
    }

    async function saveDrawing() {
        window.clearTimeout(saveTimer);
        setStatus("Saving...", "is-saving");
        redrawNow();

        const title = getNormalizedTitle();
        titleInput.value = title;
        const payload = {
            title,
            drawing_data_json: { elements, backgroundColor, canvasSize },
            preview_image: canvas.toDataURL("image/png"),
        };

        const response = await fetch(saveUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken,
            },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            setStatus("Save failed", "is-unsaved");
            return false;
        }

        isDirty = false;
        setStatus("Saved", "");
        return true;
    }

    canvas.addEventListener("pointerdown", startElement);
    canvas.addEventListener("pointermove", moveElement);
    canvas.addEventListener("pointerup", finishElement);
    canvas.addEventListener("pointercancel", finishElement);
    canvas.addEventListener("pointerleave", finishElement);

    toolButtons.forEach((button) => {
        button.addEventListener("click", () => {
            setPanMode(false);
            setActiveTool(button.dataset.tool);
        });
    });

    brushColorInput.addEventListener("input", () => {
        setBrushColor(brushColorInput.value);
    });

    colorSwatches.forEach((swatch) => {
        swatch.addEventListener("click", () => {
            setBrushColor(swatch.dataset.colorSwatch);
            if (activeTool === "eraser") {
                setActiveTool("brush");
            }
        });
    });

    backgroundColorInput.addEventListener("input", () => {
        backgroundColor = backgroundColorInput.value;
        document.documentElement.style.setProperty("--active-bg-color", backgroundColor);
        markDirty();
        redraw();
    });

    brushSizeInput.addEventListener("input", () => {
        sizeValue.textContent = brushSizeInput.value;
    });

    canvasSizeInput.addEventListener("change", () => {
        applyCanvasSize(parseCanvasSize(canvasSizeInput.value), true);
    });

    zoomOutButton.addEventListener("click", () => {
        setCanvasZoom(canvasZoom - zoomStep);
    });

    zoomInButton.addEventListener("click", () => {
        setCanvasZoom(canvasZoom + zoomStep);
    });

    zoomResetButton.addEventListener("click", fitCanvas);

    panButton.addEventListener("click", () => {
        setPanMode(!isPanMode);
    });

    async function toggleCanvasFullscreen() {
        if (
            !canvasViewport.requestFullscreen ||
            !document.exitFullscreen ||
            shell.classList.contains("is-recovery-open")
        ) {
            return;
        }

        try {
            if (!document.fullscreenElement) {
                await canvasViewport.requestFullscreen();
            } else if (document.fullscreenElement === canvasViewport) {
                await document.exitFullscreen();
            }
        } catch (error) {
            // Fullscreen can be denied by the browser; drawing should continue normally.
        }
    }

    fullscreenButton.addEventListener("click", toggleCanvasFullscreen);

    exitFullscreenButton.addEventListener("click", async () => {
        if (document.fullscreenElement === canvasViewport && document.exitFullscreen) {
            await document.exitFullscreen();
        }
    });

    canvas.addEventListener("dblclick", (event) => {
        event.preventDefault();
        toggleCanvasFullscreen();
    });

    document.addEventListener("fullscreenchange", () => {
        const isFullscreen = document.fullscreenElement === canvasViewport;
        canvasViewport.classList.toggle("is-fullscreen", isFullscreen);
        fullscreenButton.classList.toggle("is-active", isFullscreen);
        fullscreenButton.setAttribute("aria-pressed", String(isFullscreen));
        if (zoomMode === "fit" || isFullscreen) {
            fitCanvas();
        } else {
            syncCanvasSurface();
        }
    });

    undoButton.addEventListener("click", undoLast);

    clearButton.addEventListener("click", () => {
        clearConfirmModal.classList.remove("is-hidden");
    });

    cancelClearButton.addEventListener("click", () => {
        clearConfirmModal.classList.add("is-hidden");
    });

    confirmClearButton.addEventListener("click", () => {
        clearCanvas();
        clearConfirmModal.classList.add("is-hidden");
    });

    clearConfirmModal.addEventListener("click", (event) => {
        if (event.target === clearConfirmModal) {
            clearConfirmModal.classList.add("is-hidden");
        }
    });

    fillButton.addEventListener("click", fillCanvas);

    cancelTextButton.addEventListener("click", () => {
        pendingTextPoint = null;
        textModal.classList.add("is-hidden");
    });

    confirmTextButton.addEventListener("click", commitText);

    textInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            commitText();
        }
    });

    textModal.addEventListener("click", (event) => {
        if (event.target === textModal) {
            pendingTextPoint = null;
            textModal.classList.add("is-hidden");
        }
    });

    moreToggle.addEventListener("click", () => {
        const isOpen = moreToggle.getAttribute("aria-expanded") === "true";
        moreToggle.setAttribute("aria-expanded", String(!isOpen));
        morePanel.hidden = isOpen;
        morePanel.classList.toggle("is-hidden", isOpen);
    });

    symmetryToggle.addEventListener("click", () => {
        symmetryEnabled = !symmetryEnabled;
        const label = symmetryToggle.querySelector("span");
        label.textContent = symmetryEnabled ? "Symmetry On" : "Symmetry Off";
        symmetryToggle.classList.toggle("is-active", symmetryEnabled);
        symmetryToggle.setAttribute("aria-pressed", String(symmetryEnabled));
    });

    titleInput.addEventListener("input", markDirty);
    saveButton.addEventListener("click", saveDrawing);

    publishButton.addEventListener("click", async () => {
        const title = getNormalizedTitle();
        if (!title) {
            publishMessage.textContent = "Add a title before publishing your drawing.";
            titleInput.focus();
            return;
        }

        publishButton.disabled = true;
        publishButton.textContent = "Publishing...";
        if (isDirty) {
            const saved = await saveDrawing();
            if (!saved) {
                publishButton.disabled = false;
                publishButton.textContent = "Publish Drawing";
                publishMessage.textContent = "Save failed. Fix that first, then publish again.";
                return;
            }
        }

        const response = await fetch(publishUrl, {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken },
        });

        const data = await response.json();
        if (response.ok && data.ok) {
            publishButton.textContent = "Published";
            publishMessage.textContent = "Your drawing is now public in the showcase.";
        } else {
            publishButton.disabled = false;
            publishButton.textContent = "Publish Drawing";
            publishMessage.textContent = data.error || "Publish failed. Save and try again.";
        }
    });

    copyButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            if (!passKey) return;
            await navigator.clipboard.writeText(passKey.textContent.trim());
            const originalLabel = button.textContent;
            button.textContent = "Copied!";
            window.setTimeout(() => {
                button.textContent = originalLabel;
            }, 1400);
        });
    });

    if (downloadButton && passKey) {
        downloadButton.addEventListener("click", () => {
            const blob = new Blob([`masdraw recovery key\n\n${passKey.textContent.trim()}\n`], { type: "text/plain" });
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = "masdraw-recovery-key.txt";
            link.click();
            URL.revokeObjectURL(link.href);
        });
    }

    if (closeModalButton && recoveryModal) {
        document.body.style.overflow = "hidden";
        closeModalButton.addEventListener("click", () => {
            recoveryModal.classList.add("is-hidden");
            shell.classList.remove("is-recovery-open");
            document.body.style.overflow = "";
        });
    }

    window.addEventListener("resize", () => {
        if (zoomMode === "fit") {
            fitCanvas();
        } else {
            syncCanvasSurface();
        }
    });
    backgroundColorInput.value = backgroundColor;
    setBrushColor(brushColorInput.value);
    document.documentElement.style.setProperty("--active-bg-color", backgroundColor);
    morePanel.classList.toggle("is-hidden", morePanel.hidden);
    setActiveTool("brush");
    applyCanvasSize(canvasSize);
}
