/* Life OS — Telegram Mini App v2 */

const tg = window.Telegram?.WebApp;
const initData = tg?.initData || "";
const initDataUnsafe = tg?.initDataUnsafe || {};

const urlUid = new URLSearchParams(window.location.search).get("uid");
const userId = initDataUnsafe?.user?.id || urlUid || null;

if (tg) {
    tg.ready();
    tg.expand();
    tg.enableClosingConfirmation();
}

// === API ===

async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (initData) headers["X-Telegram-Init-Data"] = initData;
    if (!initData && userId) headers["X-Telegram-User-Id"] = String(userId);
    const res = await fetch(path, { ...options, headers });
    if (!res.ok) {
        let detail = `API ${res.status}`;
        try { const body = await res.json(); if (body.reason) detail += ` (${body.reason})`; } catch (_) {}
        throw new Error(detail);
    }
    return res.json();
}

// === Tabs ===

const tabs = document.querySelectorAll(".tab");
const contents = document.querySelectorAll(".tab-content");
const cache = {};

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

async function loadTab(name) {
    if (cache[name]) return;
    try {
        switch (name) {
            case "tasks": await loadTasks(); break;
            case "projects": await loadProjects(); break;
            case "health": await loadHealth(); break;
            case "goals": await loadGoals(); break;
            case "finances": await loadFinances(); break;
            case "chat": initChat(); break;
        }
        cache[name] = true;
    } catch (e) {
        console.error("Load error:", name, e);
        const container = document.getElementById(`tab-${name}`);
        if (container && !container.querySelector(".error-state")) {
            const errDiv = document.createElement("div");
            errDiv.className = "error-state";
            errDiv.textContent = e.message.includes("401") ? "⚠️ Ошибка авторизации" : `⚠️ ${e.message}`;
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

    // Overdue
    const overdueSection = document.getElementById("overdue-section");
    const overdueList = document.getElementById("overdue-list");
    if (data.overdue && data.overdue.length) {
        overdueSection.classList.remove("hidden");
        document.getElementById("overdue-count").textContent = data.overdue.length;
        overdueList.innerHTML = data.overdue.map(t => renderTaskItem(t, true)).join("");
    }

    // Today
    const todayCount = document.getElementById("today-count");
    todayCount.textContent = data.tasks.length || "";
    renderTasks(data.tasks);

    // Tomorrow
    const tomorrowSection = document.getElementById("tomorrow-section");
    if (data.tomorrow && data.tomorrow.length) {
        tomorrowSection.classList.remove("hidden");
        document.getElementById("tomorrow-count").textContent = data.tomorrow.length;
        document.getElementById("tomorrow-list").innerHTML = data.tomorrow.map(t => renderTaskItem(t, false)).join("");
    }

    // Inbox
    const inboxSection = document.getElementById("inbox-section");
    if (data.inbox && data.inbox.length) {
        inboxSection.classList.remove("hidden");
        document.getElementById("inbox-count").textContent = data.inbox.length;
        document.getElementById("inbox-list").innerHTML = data.inbox.map(t => renderTaskItem(t, false)).join("");
    }
}

function renderTaskItem(t, isOverdue) {
    const doneClass = t.is_done ? "done" : "";
    const checkClass = t.is_done ? "checked" : "";
    const time = t.due_time ? t.due_time.slice(0, 5) : "";
    const project = t.project_name ? `<span class="task-project">📁 ${escapeHtml(t.project_name)}</span>` : "";
    const overdueDate = isOverdue && t.due_date ? `<span class="task-overdue-date">${formatDate(t.due_date)}</span>` : "";
    const priorityDot = t.priority === "critical" ? "🔴" : t.priority === "high" ? "🟠" : "";

    return `
        <div class="list-item ${doneClass} ${isOverdue ? 'overdue-item' : ''}" data-task-id="${t.id}">
            <button class="task-checkbox ${checkClass}" onclick="toggleTask(${t.id}, ${!t.is_done})">
                ${t.is_done ? "✓" : ""}
            </button>
            <div class="task-content">
                <span class="task-text">${priorityDot} ${escapeHtml(t.task_text)}</span>
                ${project || overdueDate ? `<div class="task-meta">${project}${overdueDate}</div>` : ""}
            </div>
            ${time ? `<span class="task-time">${time}</span>` : ""}
        </div>
    `;
}

function renderTasks(tasks) {
    const list = document.getElementById("tasks-list");
    const stats = document.getElementById("tasks-stats");

    if (!tasks.length) {
        list.innerHTML = '<div class="empty-state">Нет задач на сегодня 🎉</div>';
        stats.textContent = "";
        return;
    }

    tasks.sort((a, b) => {
        if (a.is_done !== b.is_done) return a.is_done ? 1 : -1;
        const ta = a.due_time || "99:99";
        const tb = b.due_time || "99:99";
        return ta.localeCompare(tb);
    });

    list.innerHTML = tasks.map(t => renderTaskItem(t, false)).join("");

    const done = tasks.filter(t => t.is_done).length;
    const pct = Math.round(done / tasks.length * 100);
    stats.innerHTML = `
        <div class="progress-bar thin"><div class="progress-fill" style="width:${pct}%"></div></div>
        <span>Выполнено: ${done}/${tasks.length}</span>
    `;
}

async function toggleTask(taskId, complete) {
    try {
        if (complete) await api(`/api/webapp/tasks/${taskId}/complete`, { method: "POST" });
        cache.tasks = false;
        await loadTasks();
        if (tg) tg.HapticFeedback?.impactOccurred("light");
    } catch (e) { console.error("Toggle task error:", e); }
}

function toggleTomorrow() {
    const list = document.getElementById("tomorrow-list");
    const icon = document.getElementById("tomorrow-toggle");
    list.classList.toggle("collapsed");
    icon.textContent = list.classList.contains("collapsed") ? "▼" : "▲";
}

function toggleInbox() {
    const list = document.getElementById("inbox-list");
    const icon = document.getElementById("inbox-toggle");
    list.classList.toggle("collapsed");
    icon.textContent = list.classList.contains("collapsed") ? "▼" : "▲";
}

// === Add task form ===

const btnAdd = document.getElementById("btn-add-task");
const addForm = document.getElementById("add-task-form");
const btnSubmit = document.getElementById("btn-submit-task");

btnAdd.addEventListener("click", () => {
    addForm.classList.toggle("hidden");
    if (!addForm.classList.contains("hidden")) {
        document.getElementById("new-task-text").focus();
        document.getElementById("new-task-date").value = new Date().toISOString().split("T")[0];
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
            body: JSON.stringify({ text, due_date: date || null, priority }),
        });
        document.getElementById("new-task-text").value = "";
        addForm.classList.add("hidden");
        cache.tasks = false;
        await loadTasks();
        if (tg) tg.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
        console.error("Create task error:", e);
        if (tg) tg.HapticFeedback?.notificationOccurred("error");
    } finally { btnSubmit.disabled = false; }
});

// === Projects ===

async function loadProjects() {
    const data = await api("/api/webapp/projects");
    const list = document.getElementById("projects-list");
    document.getElementById("projects-count").textContent = data.projects.length || "";

    if (!data.projects || !data.projects.length) {
        list.innerHTML = '<div class="empty-state">Нет активных проектов</div>';
        return;
    }

    const typeLabels = { solo: "👤 Личный", partnership: "🤝 Партнёрский", family: "👨‍👩‍👦 Семейный", asset: "🏠 Актив" };

    list.innerHTML = data.projects.map(p => {
        const totalTasks = (p.active_tasks || 0) + (p.done_tasks || 0);
        const taskInfo = totalTasks > 0
            ? `<span class="project-stat">📋 ${p.done_tasks}/${totalTasks}</span>`
            : `<span class="project-stat dim">📋 0 задач</span>`;

        const balance = (p.total_income || 0) - (p.total_expense || 0);
        const finInfo = (p.total_income || p.total_expense)
            ? `<span class="project-stat ${balance >= 0 ? 'income' : 'expense'}">${balance >= 0 ? '+' : ''}${formatMoney(balance)} ₽</span>`
            : "";

        const typeLabel = typeLabels[p.type] || "📁 Проект";

        return `
            <div class="list-item project-card clickable" onclick="openProjectDetail(${p.project_id}, '${escapeAttr(p.name)}')">
                <div class="project-main">
                    <div class="project-name">${escapeHtml(p.name)}</div>
                    <div class="project-type">${typeLabel}</div>
                </div>
                <div class="project-stats">
                    ${taskInfo}
                    ${finInfo}
                    <span class="project-arrow">›</span>
                </div>
            </div>
        `;
    }).join("");
}

// === Health ===

async function loadHealth() {
    const data = await api("/api/webapp/health");

    // Targets
    const kcal = data.total_kcal || 0;
    const water = data.water_ml || 0;
    document.getElementById("health-kcal-val").textContent = kcal;
    document.getElementById("health-water-val").textContent = water;
    document.getElementById("health-kcal-bar").style.width = `${Math.min(100, kcal / 2000 * 100)}%`;
    document.getElementById("health-water-bar").style.width = `${Math.min(100, water / 2000 * 100)}%`;

    // Watch metrics
    let steps = null;
    if (data.watch && data.watch.length) {
        const extras = document.getElementById("watch-extras");
        extras.classList.remove("hidden");
        const latest = data.watch[data.watch.length - 1];
        const jd = typeof latest.json_data === "string" ? JSON.parse(latest.json_data) : (latest.json_data || {});

        steps = jd.steps;
        if (jd.heart_rate != null) document.getElementById("watch-hr").textContent = `${jd.heart_rate} уд/мин`;
        if (jd.spo2 != null) document.getElementById("watch-spo2").textContent = `${jd.spo2}%`;
        if (jd.stress != null) document.getElementById("watch-stress").textContent = jd.stress;
    }

    // Steps target
    if (steps != null) {
        document.getElementById("health-steps-val").textContent = steps.toLocaleString();
        document.getElementById("health-steps-bar").style.width = `${Math.min(100, steps / 10000 * 100)}%`;
    }

    // Meals
    const mealsList = document.getElementById("meals-list");
    if (data.meals && data.meals.length) {
        mealsList.innerHTML = data.meals.map(m => {
            const jd = typeof m.json_data === "string" ? JSON.parse(m.json_data) : (m.json_data || {});
            const name = jd.food_name || m.raw_text || "Приём пищи";
            const kcalStr = jd.calories ? `${jd.calories} ккал` : "";
            return `<div class="list-item"><span class="task-text">${escapeHtml(name)}</span><span class="task-time">${kcalStr}</span></div>`;
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
        const tasksLine = g.total_tasks > 0
            ? `<span class="goal-tasks">📋 ${g.done_tasks}/${g.total_tasks} задач</span>`
            : "";
        const daysLeft = g.target_date ? daysUntil(g.target_date) : null;
        const daysLine = daysLeft != null
            ? `<span class="goal-days ${daysLeft < 7 ? 'urgent' : ''}">${daysLeft > 0 ? `⏰ ${daysLeft} дн` : '⚠️ Срок!'}</span>`
            : "";

        return `
            <div class="list-item goal-card">
                <div class="goal-header">
                    <span class="goal-name">${icon} ${escapeHtml(g.title)}</span>
                    <span class="goal-pct">${pct}%</span>
                </div>
                <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                ${tasksLine || daysLine ? `<div class="goal-meta">${tasksLine}${daysLine}</div>` : ""}
            </div>
        `;
    }).join("");
}

// === Finances ===

async function loadFinances() {
    const data = await api("/api/webapp/finances");

    // Monthly summary
    if (data.monthly) {
        const card = document.getElementById("monthly-summary");
        card.classList.remove("hidden");
        const m = data.monthly;
        const balance = (m.income || 0) - (m.expense || 0);
        const monthNames = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
        const now = new Date();
        document.getElementById("monthly-title").textContent = `${monthNames[now.getMonth()]} ${now.getFullYear()}`;
        document.getElementById("monthly-income").textContent = `+${formatMoney(m.income)} ₽`;
        document.getElementById("monthly-expense").textContent = `−${formatMoney(m.expense)} ₽`;
        const balEl = document.getElementById("monthly-balance");
        balEl.textContent = `💰 Баланс: ${balance >= 0 ? '+' : ''}${formatMoney(balance)} ₽`;
        balEl.className = `monthly-balance ${balance >= 0 ? 'income' : 'expense'}`;
    }

    // Categories breakdown
    if (data.categories && data.categories.length) {
        const section = document.getElementById("categories-section");
        section.classList.remove("hidden");
        const catList = document.getElementById("categories-list");
        const maxAmount = Math.max(...data.categories.map(c => parseFloat(c.total)));
        catList.innerHTML = data.categories.map(c => {
            const total = parseFloat(c.total);
            const pct = maxAmount > 0 ? (total / maxAmount * 100) : 0;
            return `
                <div class="category-row">
                    <div class="category-info">
                        <span class="category-name">${escapeHtml(c.category)}</span>
                        <span class="category-amount">${formatMoney(total)} ₽</span>
                    </div>
                    <div class="category-bar"><div class="category-fill" style="width:${pct}%"></div></div>
                </div>
            `;
        }).join("");
    }

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

// === Project Detail ===

let currentProjectId = null;

async function openProjectDetail(projectId, projectName) {
    currentProjectId = projectId;
    document.getElementById("project-detail-name").textContent = projectName;
    document.getElementById("project-detail").classList.remove("hidden");
    document.getElementById("project-task-text").value = "";
    document.getElementById("project-task-date").value = new Date().toISOString().split("T")[0];
    if (tg) tg.HapticFeedback?.impactOccurred("light");
    await loadProjectTasks(projectId);
}

function closeProjectDetail() {
    document.getElementById("project-detail").classList.add("hidden");
    currentProjectId = null;
}

async function loadProjectTasks(projectId) {
    const list = document.getElementById("project-tasks-list");
    list.innerHTML = '<div class="loading-inline">Загрузка...</div>';
    try {
        const data = await api(`/api/webapp/projects/${projectId}/tasks`);
        if (!data.tasks || !data.tasks.length) {
            list.innerHTML = '<div class="empty-state">Нет задач в проекте</div>';
            return;
        }
        list.innerHTML = data.tasks.map(t => renderTaskItem(t, false)).join("");
    } catch (e) {
        list.innerHTML = `<div class="error-state">⚠️ ${e.message}</div>`;
    }
}

document.getElementById("btn-project-add-task")?.addEventListener("click", async () => {
    const text = document.getElementById("project-task-text").value.trim();
    if (!text || !currentProjectId) return;
    const date = document.getElementById("project-task-date").value;
    const priority = document.getElementById("project-task-priority").value;
    const btn = document.getElementById("btn-project-add-task");
    try {
        btn.disabled = true;
        await api("/api/webapp/tasks", {
            method: "POST",
            body: JSON.stringify({ text, due_date: date || null, priority, project_id: currentProjectId }),
        });
        document.getElementById("project-task-text").value = "";
        await loadProjectTasks(currentProjectId);
        cache.tasks = false;
        cache.projects = false;
        if (tg) tg.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
        console.error("Add project task error:", e);
        if (tg) tg.HapticFeedback?.notificationOccurred("error");
    } finally { btn.disabled = false; }
});

// === Chat ===

let chatInitialized = false;

function initChat() {
    if (chatInitialized) return;
    chatInitialized = true;

    const input = document.getElementById("chat-input");
    const btn = document.getElementById("btn-send-chat");

    btn.addEventListener("click", sendChatMessage);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });
}

async function sendChatMessage() {
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;

    const messagesDiv = document.getElementById("chat-messages");

    // Remove welcome message on first send
    const welcome = messagesDiv.querySelector(".chat-welcome");
    if (welcome) welcome.remove();

    // Add user bubble
    appendChatBubble(message, "user");
    input.value = "";
    input.focus();

    // Add typing indicator
    const typing = document.createElement("div");
    typing.className = "chat-bubble assistant typing";
    typing.innerHTML = '<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>';
    messagesDiv.appendChild(typing);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    try {
        const data = await api("/api/webapp/chat", {
            method: "POST",
            body: JSON.stringify({ message }),
        });
        typing.remove();
        appendChatBubble(data.reply, "assistant");
        if (tg) tg.HapticFeedback?.impactOccurred("light");
    } catch (e) {
        typing.remove();
        appendChatBubble("⚠️ Ошибка: " + e.message, "assistant error");
    }
}

function appendChatBubble(text, role) {
    const messagesDiv = document.getElementById("chat-messages");
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    bubble.textContent = text;
    messagesDiv.appendChild(bubble);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// === Utils ===

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    return text.replace(/'/g, "\\'").replace(/"/g, '\\"');
}

function formatMoney(n) {
    return Number(n).toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

function formatDate(dateStr) {
    const d = new Date(dateStr);
    return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

function daysUntil(dateStr) {
    const target = new Date(dateStr);
    const now = new Date();
    return Math.ceil((target - now) / 86400000);
}

// === Init ===

document.addEventListener("DOMContentLoaded", async () => {
    try {
        await loadTasks();
    } finally {
        document.getElementById("loader").classList.add("hidden");
    }
});
