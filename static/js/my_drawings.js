const drawingCards = Array.from(document.querySelectorAll("[data-drawing-card]"));
const drawingFilterButtons = Array.from(document.querySelectorAll("[data-drawing-filter]"));
const drawingSearchInput = document.querySelector("[data-drawing-search]");
const drawingEmptyFilter = document.querySelector("[data-drawing-empty-filter]");
const drawingClearButton = document.querySelector("[data-drawing-clear]");

let activeDrawingFilter = "all";

function normalizeDrawingQuery(value) {
    return value.trim().toLowerCase();
}

function updateDrawingCards() {
    const query = normalizeDrawingQuery(drawingSearchInput ? drawingSearchInput.value : "");
    let visibleCount = 0;

    drawingCards.forEach((card) => {
        const status = card.dataset.status || "private";
        const title = card.dataset.title || "";
        const matchesStatus = activeDrawingFilter === "all" || status === activeDrawingFilter;
        const matchesSearch = !query || title.includes(query);
        const isVisible = matchesStatus && matchesSearch;

        card.classList.toggle("is-hidden", !isVisible);
        if (isVisible) {
            visibleCount += 1;
        }
    });

    if (drawingEmptyFilter) {
        drawingEmptyFilter.classList.toggle("is-hidden", visibleCount !== 0);
    }
}

function setActiveDrawingFilter(filter) {
    activeDrawingFilter = filter;
    drawingFilterButtons.forEach((button) => {
        const isActive = button.dataset.drawingFilter === filter;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });
    updateDrawingCards();
}

drawingFilterButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.classList.contains("is-active")));
    button.addEventListener("click", () => {
        setActiveDrawingFilter(button.dataset.drawingFilter || "all");
    });
});

if (drawingSearchInput) {
    drawingSearchInput.addEventListener("input", updateDrawingCards);
}

if (drawingClearButton) {
    drawingClearButton.addEventListener("click", () => {
        if (drawingSearchInput) {
            drawingSearchInput.value = "";
        }
        setActiveDrawingFilter("all");
    });
}
