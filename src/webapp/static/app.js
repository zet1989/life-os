/* Life OS — Telegram Mini App */

const tg = window.Telegram?.WebApp;
const initData = tg?.initData || "";
const initDataUnsafe = tg?.initDataUnsafe || {};

// Настройка Telegram Web App
if (tg) {
    tg.ready();
    tg.expand();
    tg.enableClosingConfirmation();
}

// Debug: логируем initData
console.log("TG initData length:", initData.length);
console.log("TG initDataUnsafe:", JSON.stringify(initDataUnsafe));
console.log("TG user:", JSON.stringify(initDataUnsafe?.user));

// === API ===

async function api(path, options = {}) {
    // Собираем auth headers
    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {}),
    };
    if (initData) {
        headers["X-Telegram-Init-Data"] = initData;
    }
    // Fallback: передаём user_id напрямую если initData пуст
    if (!initData && initDataUnsafe?.user?.id) {
        headers["X-Telegram-User-Id"] = String(initDataUnsafe.user.id);
    }
    const res = await fetch(path, {
        ...options,
        headers,
    });
    if (!res.ok) {
        let detail = `API ${res.status}`;
        try {
            const body = await res.json();
            if (body.reason) detail += ` (${body.reason}, data_len=${body.init_data_len})`;
        } catch (_) {}
        throw new Error(detail);
    }
    return res.json();
}

// === Tabs ===

const tabs = document.querySelectorAll(".tab");
const contents = document.querySelectorAll(".tab-content");

tabs.forEach(tab => {
    tab.addEventListener("click", () => {
        const target = tab.dataset.tab;
        tabs.forEach(t => t.classList.remove("active"));
        contents.forEach(c => c.classList.remove("active"));
        tab.classList.add("active");
        document.getElementById(`tab-${target}`).classList.add("active");
        loadTab(target);
    });
});

// === Data cache ===
const cache = {};

async function loadTab(name) {
    if (cache[name]) return;
    try {
        switch (name) {
            case "tasks": await loadTasks(); break;
            case "projects": await loadProjects(); break;
            case "health": await loadHealth(); break;
            case "goals": await loadGoals(); break;
            case "finances": await loadFinances(); break;
        }
        cache[name] = true;
    } catch (e) {
        console.error("Load error:", name, e);
        const container = document.getElementById(`tab-${name}`);
        if (container && !container.querySelector(".error-state")) {
            const errDiv = document.createElement("div");
            errDiv.className = "error-state";
            errDiv.textContent = e.message.includes("401") ? "⚠️ Ошибка авторизации" : `⚠️ Ошибка загрузки: ${e.message}`;
            container.appendChild(errDiv);
        }
    }
}

// === Tasks ===

async function loadTasks() {
    const data = await api("/api/webapp/tasks");

    // Focus
    const focusBlock = document.getElementById("focus-block");
    const focusText = document.getElementById("focus-text");
    if (data.focus && data.focus.focus_text) {
        focusText.textContent = data.focus.focus_text;
        focusBlock.classList.remove("hidden");
    }

    renderTasks(data.tasks);
}

function renderTasks(tasks) {
    const list = document.getElementById("tasks-list");
    const stats = document.getElementById("tasks-stats");

    if (!tasks.length) {
        list.innerHTML = '<div class="empty-state">Нет задач на сегодня 🎉</div>';
        stats.textContent = "";
        return;
    }

    // Сортировка: невыполненные первые, потом по времени
    tasks.sort((a, b) => {
        if (a.is_done !== b.is_done) return a.is_done ? 1 : -1;
        const ta = a.due_time || "99:99";
        const tb = b.due_time || "99:99";
        return ta.localeCompare(tb);
    });

    list.innerHTML = tasks.map(t => {
        const priorityClass = `priority-${t.priority || "normal"}`;
        const doneClass = t.is_done ? "done" : "";
        const checkClass = t.is_done ? "checked" : "";
        const time = t.due_time ? t.due_time.slice(0, 5) : "";
        const tags = (t.tags || []).map(tag => `<span class="task-tag">#${tag}</span>`).join(" ");

        return `
            <div class="list-item ${doneClass}" data-task-id="${t.id}">
                <button class="task-checkbox ${checkClass}" onclick="toggleTask(${t.id}, ${!t.is_done})">
                    ${t.is_done ? "✓" : ""}
                </button>
                <span class="task-text">${escapeHtml(t.task_text)}${tags ? " " + tags : ""}</span>
                ${time ? `<span class="task-time">${time}</span>` : ""}
                <span class="task-priority ${priorityClass}"></span>
            </div>
        `;
    }).join("");

    const done = tasks.filter(t => t.is_done).length;
    stats.textContent = `Выполнено: ${done}/${tasks.length}`;
}

async function toggleTask(taskId, complete) {
    try {
        if (complete) {
            await api(`/api/webapp/tasks/${taskId}/complete`, { method: "POST" });
        }
        // Обновляем UI
        cache.tasks = false;
        await loadTasks();
        if (tg) tg.HapticFeedback?.impactOccurred("light");
    } catch (e) {
        console.error("Toggle task error:", e);
    }
}

// === Add task form ===

const btnAdd = document.getElementById("btn-add-task");
const addForm = document.getElementById("add-task-form");
const btnSubmit = document.getElementById("btn-submit-task");

btnAdd.addEventListener("click", () => {
    addForm.classList.toggle("hidden");
    if (!addForm.classList.contains("hidden")) {
        document.getElementById("new-task-text").focus();
        // Установить сегодняшнюю дату
        const today = new Date().toISOString().split("T")[0];
        document.getElementById("new-task-date").value = today;
    }
});

btnSubmit.addEventListener("click", async () => {
    const text = document.getElementById("new-task-text").value.trim();
    if (!text) return;

    const date = document.getElementById("new-task-date").value;
    const priority = document.getElementById("new-task-priority").value;

    try {
        btnSubmit.disabled = true;
        await api("/api/webapp/tasks", {
            method: "POST",
            body: JSON.stringify({
                text,
                due_date: date || null,
                priority,
            }),
        });

        document.getElementById("new-task-text").value = "";
        addForm.classList.add("hidden");
        cache.tasks = false;
        await loadTasks();
        if (tg) tg.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
        console.error("Create task error:", e);
        if (tg) tg.HapticFeedback?.notificationOccurred("error");
    } finally {
        btnSubmit.disabled = false;
    }
});

// === Projects ===

async function loadProjects() {
    const data = await api("/api/webapp/projects");
    const list = document.getElementById("projects-list");

    if (!data.projects || !data.projects.length) {
        list.innerHTML = '<div class="empty-state">Нет активных проектов</div>';
        return;
    }

    const typeIcons = { solo: "👤", partnership: "🤝", family: "👨‍👩‍👦", asset: "🏠" };

    list.innerHTML = data.projects.map(p => {
        const icon = typeIcons[p.type] || "📁";
        const meta = p.metadata || {};
        const details = [];
        if (p.type === "asset" && meta.address) details.push(meta.address);
        if (meta.vin) details.push(`VIN: ${meta.vin}`);
        const statusClass = p.status === "active" ? "project-active" : "project-paused";

        return `
            <div class="list-item project-item">
                <div class="project-icon">${icon}</div>
                <div class="project-info">
                    <div class="project-name">${escapeHtml(p.name)}</div>
                    ${details.length ? `<div class="project-meta">${escapeHtml(details.join(" · "))}</div>` : ""}
                </div>
                <span class="project-status ${statusClass}">${p.status === "active" ? "●" : "⏸"}</span>
            </div>
        `;
    }).join("");
}

// === Health ===

async function loadHealth() {
    const data = await api("/api/webapp/health");

    document.getElementById("health-kcal").textContent = data.total_kcal ? `${data.total_kcal} ккал` : "—";
    document.getElementById("health-water").textContent = data.water_ml ? `${data.water_ml} мл` : "—";

    // Watch metrics
    if (data.watch && data.watch.length) {
        const metricsBlock = document.getElementById("watch-metrics");
        metricsBlock.classList.remove("hidden");

        const latest = data.watch[data.watch.length - 1];
        const jd = typeof latest.json_data === "string" ? JSON.parse(latest.json_data) : (latest.json_data || {});

        document.getElementById("watch-steps").textContent = jd.steps != null ? jd.steps.toLocaleString() : "—";
        document.getElementById("watch-hr").textContent = jd.heart_rate != null ? `${jd.heart_rate} уд/мин` : "—";
    }

    // Meals
    const mealsList = document.getElementById("meals-list");
    if (data.meals && data.meals.length) {
        mealsList.innerHTML = data.meals.map(m => {
            const jd = typeof m.json_data === "string" ? JSON.parse(m.json_data) : (m.json_data || {});
            const name = jd.food_name || m.raw_text || "Приём пищи";
            const kcal = jd.calories ? `${jd.calories} ккал` : "";
            return `<div class="list-item"><span class="task-text">${escapeHtml(name)}</span><span class="task-time">${kcal}</span></div>`;
        }).join("");
    } else {
        mealsList.innerHTML = '<div class="empty-state">Пока ничего не записано</div>';
    }

    // Workouts
    const workoutsList = document.getElementById("workouts-list");
    if (data.workouts && data.workouts.length) {
        workoutsList.innerHTML = data.workouts.map(w => {
            const jd = typeof w.json_data === "string" ? JSON.parse(w.json_data) : (w.json_data || {});
            const name = jd.workout_type || w.raw_text || "Тренировка";
            const duration = jd.duration_min ? `${jd.duration_min} мин` : "";
            return `<div class="list-item"><span class="task-text">${escapeHtml(name)}</span><span class="task-time">${duration}</span></div>`;
        }).join("");
    } else {
        workoutsList.innerHTML = '<div class="empty-state">Нет тренировок сегодня</div>';
    }
}

// === Goals ===

async function loadGoals() {
    const data = await api("/api/webapp/goals");
    const list = document.getElementById("goals-list");

    if (!data.goals || !data.goals.length) {
        list.innerHTML = '<div class="empty-state">Нет активных целей</div>';
        return;
    }

    const typeIcons = { dream: "🌟", yearly_goal: "📅", habit_target: "🔄" };

    list.innerHTML = data.goals.map(g => {
        const pct = g.progress_pct || 0;
        const icon = typeIcons[g.type] || "🎯";
        return `
            <div class="list-item goal-item">
                <div class="goal-header">
                    <span class="goal-name">${icon} ${escapeHtml(g.title)}</span>
                    <span class="goal-pct">${pct}%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${pct}%"></div>
                </div>
            </div>
        `;
    }).join("");
}

// === Finances ===

async function loadFinances() {
    const data = await api("/api/webapp/finances");

    // Debts summary
    const debtsCard = document.getElementById("debts-summary");
    if (data.debts_summary && (data.debts_summary.total_debt || data.debts_summary.total_credit)) {
        debtsCard.classList.remove("hidden");
        const ds = data.debts_summary;
        debtsCard.innerHTML = `
            <h3>💳 Долги и кредиты</h3>
            ${ds.total_credit ? `<div>🏦 Кредиты: ${formatMoney(ds.total_credit)} ₽</div>` : ""}
            ${ds.total_debt ? `<div>📋 Должны мне: ${formatMoney(ds.total_debt)} ₽</div>` : ""}
        `;
    }

    // Transactions
    const list = document.getElementById("finances-list");
    if (!data.transactions || !data.transactions.length) {
        list.innerHTML = '<div class="empty-state">Нет транзакций</div>';
        return;
    }

    list.innerHTML = data.transactions.map(t => {
        const isIncome = t.transaction_type === "income";
        const sign = isIncome ? "+" : "−";
        const cls = isIncome ? "income" : "expense";
        const amount = Math.abs(parseFloat(t.amount) || 0);
        const cat = t.category || "";
        const date = t.timestamp ? new Date(t.timestamp).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) : "";

        return `
            <div class="list-item finance-item">
                <div>
                    <div class="task-text">${escapeHtml(t.description || cat)}</div>
                    <div class="finance-meta">${cat} · ${date}</div>
                </div>
                <div class="finance-amount ${cls}">${sign}${formatMoney(amount)} ₽</div>
            </div>
        `;
    }).join("");
}

// === Utils ===

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function formatMoney(n) {
    return Number(n).toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

// === Init ===

document.addEventListener("DOMContentLoaded", async () => {
    try {
        await loadTasks();
    } finally {
        document.getElementById("loader").classList.add("hidden");
    }
});
