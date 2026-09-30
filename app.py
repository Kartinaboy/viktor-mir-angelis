from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from core.actions import create_task, edit_task, reconcile_cost, save_settings
from core.engine import budget_totals, call_charge, connection_test, eligible_tasks, execute_run, pause_all, recover_expired, start_run
from core.llm import ResponsesLLM
from core.models import ROLES, json_text
from core.scheduler import next_jobs
from core.storage import projections, store_from_credentials

st.set_page_config(page_title="Ангелис · арт-директор Viktor Mir", page_icon="A", layout="wide")
SECTIONS = ["TODAY", "BACKLOG", "STRATEGY", "RESEARCH", "CONTENT", "ART", "TATTOO", "JOURNAL", "COSTS", "SETTINGS"]


def credentials():
    keys = ["OPENAI_API_KEY", "GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_DATA_BRANCH", "APP_PASSWORD", "ANGELIS_STORAGE", "ANGELIS_DATA_DIR"]
    values = {key: os.environ[key] for key in keys if key in os.environ}
    try:
        values.update({key: str(st.secrets[key]) for key in keys if key in st.secrets})
    except FileNotFoundError:
        pass
    values.setdefault("ANGELIS_STORAGE", "github")
    return values


@st.cache_resource
def connect(values):
    return store_from_credentials(values)


@st.cache_resource
def workers():
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="angelis")


def perform(action, *args, **kwargs):
    try:
        result = action(*args, **kwargs)
        st.session_state["notice"] = "Сохранено"
        st.rerun()
    except Exception as error:
        st.error(str(error))
        return None


def launch(store, secrets, *, mode="normal", task_id=None, instruction="", domain="custom"):
    try:
        llm = None if mode == "dry" else ResponsesLLM(secrets.get("OPENAI_API_KEY", ""))
        run_id = start_run(store, mode=mode, task_id=task_id, instruction=instruction, custom_domain=domain)
        workers().submit(execute_run, store, run_id, llm)
        st.session_state["selected_run"] = run_id
        st.rerun()
    except Exception as error:
        st.error(str(error))


def artifacts_view(data, kinds=None):
    items = sorted(data["artifacts"].values(), key=lambda a: a["created_at"], reverse=True)
    if kinds:
        items = [a for a in items if a["type"] in kinds]
    if not items:
        st.info("Материалов пока нет. Они появятся после первого завершённого запуска.")
        return
    labels = {a["id"]: f"{a['title']} · {a['created_at'][:16]}" for a in items}
    selected = st.selectbox("Материал", list(labels), format_func=labels.get)
    artifact = data["artifacts"][selected]
    st.caption(f"{artifact['path']} · {artifact['model']} · {artifact['role']} · {artifact['review_status']}")
    tabs = st.tabs(["Читать", "Исходный текст", "Метаданные"])
    with tabs[0]:
        if artifact["path"].endswith(".md"):
            st.markdown(artifact["content"], unsafe_allow_html=False)
        elif artifact["path"].endswith(".json"):
            st.json(json.loads(artifact["content"]))
        else:
            st.text(artifact["content"])
        if artifact.get("sources"):
            st.caption("Источники API web search")
            for source in artifact["sources"]:
                if source["url"].startswith(("https://", "http://")):
                    st.link_button(source.get("title") or source["url"], source["url"])
    with tabs[1]:
        st.code(artifact["content"], language="json" if artifact["path"].endswith(".json") else "markdown")
    with tabs[2]:
        st.json({k: v for k, v in artifact.items() if k != "content"})
    st.download_button("Скачать файл", artifact["content"], file_name=artifact["path"].split("/")[-1], mime="text/plain", key=f"dl-{selected}")


def active_panel(store):
    data = store.load()
    runs = sorted(data["runs"].values(), key=lambda r: r["started_at"], reverse=True)
    if not runs:
        st.caption("Первый запуск ещё не выполнен")
        return
    active = next((r for r in runs if r["status"] in {"queued", "running"}), None)
    if st.session_state.get("polling") and not active:
        st.session_state["polling"] = False
        st.rerun()
    run = active or data["runs"].get(st.session_state.get("selected_run")) or runs[0]
    st.subheader("Активный запуск" if active else "Последний запуск")
    st.write(f"**{run['task']['ID']}** · {run['status']} · {run['stage']}")
    st.write(run["task"]["task"])
    if run.get("summary"):
        st.write(run["summary"])
    if run.get("error"):
        st.error(run["error"])
    if run.get("quality_flags"):
        st.warning("Проверка идеи: " + "; ".join(run["quality_flags"]))
    events = [e for e in data["journal"] if e["run_id"] == run["id"]][-12:]
    for item in events:
        st.caption(f"{item['timestamp'][11:19]} · {item.get('stage', '')} · {item['message']}")
    if run["artifacts"]:
        for aid in run["artifacts"]:
            artifact = data["artifacts"][aid]
            st.download_button(artifact["title"], artifact["content"], artifact["path"].split("/")[-1], key=f"run-dl-{aid}")
    with st.expander("План ролей / модели"):
        st.dataframe(run["plan"], hide_index=True)


def today(data, store, secrets):
    if not data["onboarding_completed"]:
        st.info("Первый запуск: начни с Dry Run без расходов. Затем проверь API одним коротким запросом дешёвой модели.")
        if st.button("Проверить API · один короткий запрос", disabled=not secrets.get("OPENAI_API_KEY") or bool(data.get("lease"))):
            try:
                adapter = ResponsesLLM(secrets.get("OPENAI_API_KEY", ""))
                run_id = start_run(store, instruction="Маленькая проверка соединения с OpenAI", custom_tier="cheap")
                workers().submit(connection_test, store, adapter, run_id)
                st.session_state["selected_run"] = run_id
                st.session_state["notice"] = "API-тест поставлен в очередь. Результат появится в последнем запуске."
                st.rerun()
            except Exception as error:
                st.error(str(error))
    money, art = st.columns(2)
    with money:
        st.subheader("MONEY NOW")
        st.write("Текущий коммерческий двигатель: **татуировка**")
        st.caption("По STATE. Выручка, загрузка и число заявок пока не предоставлены.")
        tasks = [t for t in data["backlog"] if t["domain"] in {"commercial", "career"}]
        for task in tasks[:3]:
            st.write(f"{task['priority']} · {task['task']}")
    with art:
        st.subheader("ART CAPITAL")
        st.write(data["state"]["identity"]["strategic_destination"])
        approved = [a for a in data["artifacts"].values() if a["review_status"] == "approved" and a["type"] in {"strategy", "archive", "decision"}]
        for artifact in approved[-3:]:
            st.write("Проверенный материал: " + artifact["title"])
        st.caption("Пробелы: исходный каталог живописи, документация работ и подтверждения спроса не загружены.")
    st.divider()
    left, right = st.columns([2, 1])
    with left:
        st.subheader("Следующая работа")
        tasks = eligible_tasks(data)
        if tasks:
            st.write(f"**{tasks[0]['priority']} · {tasks[0]['ID']}**")
            st.write(tasks[0]["task"])
            st.caption("Критерий готовности: " + tasks[0]["definition_of_done"])
        instruction = st.text_area("Своя инструкция (необязательно)", placeholder="Без инструкции Ангелис выбирает приоритетную задачу из BACKLOG.")
        domain = st.selectbox("Область своей задачи", ["custom", "strategy", "career", "research", "editorial", "archive", "commercial"], disabled=not instruction.strip())
        mode = st.selectbox("Режим", ["normal", "dry", "deep"], format_func=lambda v: {"normal": "Normal", "dry": "Dry Run · без API", "deep": "Deep Strategy · Astra один раз"}[v])
        if mode == "deep":
            st.warning(f"Deep Strategy может вызвать Astra для задачи strategy/career. Лимит запуска ${data['settings']['run_budget']:.2f}. Если резерва не хватит, дорогой этап будет пропущен.")
        if st.button("Запустить Ангелис", type="primary", disabled=bool(data.get("lease"))):
            launch(store, secrets, mode=mode, instruction=instruction, domain=domain)
    with right:
        st.subheader("Последние выводы")
        for finding in data["state"].get("latest_findings", [])[-5:]:
            st.write(finding)
        if not data["state"].get("latest_findings"):
            st.caption("Новых выводов пока нет")
        st.subheader("Решения Виктора")
        for decision in data["state"]["open_decisions"][-5:]:
            st.write(decision)
        st.caption("Позиционирование и цены меняются только после твоего решения.")
    st.session_state["polling"] = bool(data.get("lease"))
    st.fragment(run_every="5s" if data.get("lease") else None)(active_panel)(store)
    with st.expander("Рабочая память STATE"):
        st.json(data["state"])


def backlog(data, store, secrets):
    statuses = st.multiselect("Статусы", ["open", "ready", "running", "blocked", "review", "done", "rejected"], default=["open", "ready", "review", "running", "blocked"])
    rows = [t for t in data["backlog"] if t["status"] in statuses]
    st.dataframe([{key: t[key] for key in ["ID", "priority", "domain", "task", "status", "model_tier", "actual_cost"]} for t in rows], hide_index=True, use_container_width=True)
    if rows:
        labels = {t["ID"]: t["ID"] + " · " + t["task"][:100] for t in rows}
        selected = st.selectbox("Задача", list(labels), format_func=labels.get)
        task = next(t for t in rows if t["ID"] == selected)
        st.write("Критерий готовности: " + task["definition_of_done"])
        with st.form("edit-task"):
            priority = st.selectbox("Приоритет", ["P0", "P1", "P2", "P3"], index=int(task["priority"][1]))
            status = st.selectbox("Статус", ["open", "ready", "blocked", "review", "done", "rejected"], index=["open", "ready", "blocked", "review", "done", "rejected"].index(task["status"]) if task["status"] != "running" else 1)
            note = st.text_input("Для done: чем подтверждено выполнение критерия")
            if st.form_submit_button("Сохранить задачу"):
                if perform(edit_task, store, selected, status=status, priority=priority, review_note=note) is None:
                    pass
        if st.button("Запустить эту задачу", disabled=task["status"] not in {"open", "ready"} or bool(data.get("lease"))):
            launch(store, secrets, task_id=selected)
    with st.expander("Новая задача"):
        with st.form("new-task"):
            title = st.text_area("Что сделать")
            definition = st.text_area("Когда задача готова")
            domain = st.selectbox("Область", ["strategy", "career", "research", "editorial", "archive", "voice", "commercial"])
            priority = st.selectbox("Приоритет новой задачи", ["P0", "P1", "P2", "P3"], index=1)
            if st.form_submit_button("Добавить"):
                perform(create_task, store, title, definition, priority, domain, "cheap" if domain == "archive" else "default")


def costs(data, store):
    totals = budget_totals(data)
    a, b, c = st.columns(3)
    a.metric("За день · оценка + резерв", f"${totals['daily']:.4f}")
    b.metric("За месяц · оценка + резерв", f"${totals['monthly']:.4f}")
    c.metric("Неизвестная стоимость · резерв", f"${totals['unknown']:.4f}")
    rows, unknown = [], []
    for run in data["runs"].values():
        for call in run["calls"]:
            usage = call.get("usage", {})
            rows.append({"run": run["id"], "model": call["model"], "role": call["role"], "status": call["status"],
                         "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                         "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
                         "search_calls": call.get("search_calls", 0), "USD / reserve": call_charge(call), "mock": run.get("mock", False)})
            if call["status"] != "settled" and run["status"] not in {"queued", "running"}:
                unknown.append((run["id"], call["id"]))
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption("Это оценка по usage API и сохранённым тарифам, а не баланс аккаунта OpenAI. После обрыва запроса резерв сохраняется, пока ты не сверишь расходы.")
    if unknown:
        with st.expander("Сверить неизвестную стоимость"):
            selected = st.selectbox("Запрос", unknown, format_func=lambda item: f"{item[0]} · {item[1]}")
            amount = st.number_input("Проверенная стоимость USD", min_value=0.0, step=0.001, format="%.6f")
            note = st.text_input("Основание сверки (например, запись в Usage OpenAI)")
            if st.button("Сохранить сверку"):
                perform(reconcile_cost, store, selected[0], selected[1], amount, note)
    with st.expander("Тарифы и дата проверки"):
        st.json(data["settings"]["pricing"])
        st.caption("Проверены " + data["settings"]["pricing_checked_at"] + ". USD за 1 млн токенов; Standard. Изменить можно в Settings.")


def journal(data):
    events = data["journal"]
    cols = st.columns(4)
    dates = sorted({e["timestamp"][:10] for e in events}, reverse=True)
    date_filter = cols[0].selectbox("Дата UTC", ["Все"] + dates)
    run_filter = cols[1].selectbox("Запуск", ["Все"] + sorted({e["run_id"] for e in events}, reverse=True))
    model_filter = cols[2].selectbox("Модель", ["Все"] + sorted({e["model"] for e in events if e["model"]}))
    role_filter = cols[3].selectbox("Роль", ["Все"] + sorted({e["role"] for e in events}))
    errors = st.checkbox("Только ошибки и бюджет")
    decisions = st.checkbox("Только решения")
    artifacts = st.checkbox("Только запись artifacts")
    selected = [e for e in events if (date_filter == "Все" or e["timestamp"].startswith(date_filter))
                and (run_filter == "Все" or e["run_id"] == run_filter)
                and (model_filter == "Все" or e["model"] == model_filter)
                and (role_filter == "Все" or e["role"] == role_filter)
                and (not errors or e["event"] in {"run_failed", "budget_warning"})
                and (not decisions or e["event"] in {"decision_requested", "backlog_updated", "cost_reconciled"})
                and (not artifacts or e["event"] == "artifact_written")]
    st.dataframe(list(reversed(selected)), hide_index=True, use_container_width=True)
    st.caption("Журнал действий: этапы, файлы, ошибки и решения. Приватные рассуждения модели не записываются.")


def settings(data, store):
    saved = data["settings"]
    if hasattr(store, "repository"):
        st.caption(f"GitHub: {store.repository} · ветка {store.branch}")
        if not store.is_private:
            st.caption("Публичное хранение: память, журнал и черновики доступны в GitHub. Пароль приложения защищает вход и запуск запросов.")
    st.write("Изменения вступают в силу после сохранения. Расписание по умолчанию выключено.")
    with st.form("settings"):
        updated = copy.deepcopy(saved)
        cols = st.columns(3)
        for col, tier, label in zip(cols, ["default", "cheap", "strategic"], ["Обычная работа", "Обслуживание", "Deep Strategy"]):
            updated["models"][tier] = col.text_input(label, saved["models"][tier])
        updated["reasoning_effort"] = st.selectbox("Reasoning effort", ["low", "medium", "high", "xhigh"], index=["low", "medium", "high", "xhigh"].index(saved["reasoning_effort"]))
        cols = st.columns(3)
        updated["daily_budget"] = cols[0].number_input("Лимит дня USD", min_value=0.01, max_value=100.0, value=float(saved["daily_budget"]), step=0.1)
        updated["run_budget"] = cols[1].number_input("Лимит запуска USD", min_value=0.01, max_value=20.0, value=float(saved["run_budget"]), step=0.05)
        updated["max_output_tokens"] = cols[2].number_input("Макс. output tokens", min_value=1000, max_value=12000, value=int(saved["max_output_tokens"]), step=500)
        updated["timezone"] = st.text_input("Часовой пояс", saved["timezone"])
        updated["web_research"] = st.checkbox("Web research через OpenAI", value=saved["web_research"])
        st.caption("Для поиска резервируется полный возможный контекст, потому что размер входа от внешних источников заранее неизвестен. При небольшом бюджете Ангелис сохранит исследовательский план без web-вызова.")
        st.subheader("Временные роли")
        role_cols = st.columns(3)
        for index, role in enumerate(ROLES):
            updated["roles"][role] = role_cols[index % 3].checkbox(role, value=saved["roles"].get(role, False))
        st.subheader("Расписание")
        updated["scheduler_enabled"] = st.checkbox("Scheduler ON", value=saved["scheduler_enabled"])
        updated["autonomous_mode"] = st.checkbox("Разрешить автономную работу", value=saved["autonomous_mode"])
        for index, job in enumerate(updated["jobs"]):
            left, right = st.columns([3, 1])
            job["enabled"] = left.checkbox(job["title"], value=job["enabled"], key=f"job-{index}")
            job["time"] = right.text_input("Время HH:MM", job["time"], key=f"job-time-{index}")
        st.caption("Облачное расписание выполняет GitHub Actions. Эти переключатели управляют разрешением работы; workflow также должен быть подключён в репозитории.")
        pricing_text = st.text_area("Тарифы: JSON (USD за 1 млн токенов)", json_text(saved["pricing"]), height=160)
        if st.form_submit_button("Сохранить настройки"):
            try:
                updated["pricing"] = json.loads(pricing_text)
                perform(save_settings, store, updated)
            except Exception as error:
                st.error(str(error))
    upcoming = next_jobs(data)
    if upcoming:
        st.dataframe(upcoming, hide_index=True)
        st.caption("Время плановое. GitHub Actions может запускаться с задержкой; пропуски не воспроизводятся спустя более 2 часов.")
    st.subheader("Полная резервная копия")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in projections(data).items():
            archive.writestr(path, text)
    st.download_button("Скачать STATE, BACKLOG, журнал и все файлы", buffer.getvalue(), "VIKTOR_MIR_ANGELIS_BACKUP.zip", "application/zip")


def main():
    secrets = credentials()
    st.title("VIKTOR MIR")
    st.caption("Ангелис · арт-директор и творческий офис")
    password = secrets.get("APP_PASSWORD", "")
    if secrets["ANGELIS_STORAGE"] == "github" and not password:
        st.info("Первое подключение: укажи ключ OpenAI, GitHub token и личный пароль в настройках нового приложения Streamlit.")
        st.markdown("Инструкция: **README.md** в репозитории. Готовый пример Secrets находится в **.streamlit/secrets.example.toml**. Настоящие ключи в файлы GitHub не вставляй.")
        st.code('OPENAI_API_KEY = "YOUR_OPENAI_KEY"\nGITHUB_TOKEN = "YOUR_FINE_GRAINED_TOKEN"\nGITHUB_REPO = "Kartinaboy/viktor-mir-angelis"\nGITHUB_DATA_BRANCH = "angelis-data"\nAPP_PASSWORD = "YOUR_PRIVATE_PASSWORD"\nANGELIS_STORAGE = "github"', language="toml")
        st.markdown("GitHub token: [создать fine-grained token](https://github.com/settings/personal-access-tokens/new), выбрать только `viktor-mir-angelis`, **Contents → Read and write**. Ключи и пароль вводи в **Streamlit → Settings → Secrets**.")
        st.stop()
    digest = hashlib.sha256(password.encode()).hexdigest() if password else ""
    if password and st.session_state.get("authenticated") != digest:
        with st.form("login", clear_on_submit=True):
            entered = st.text_input("Пароль личного офиса", type="password")
            if st.form_submit_button("Открыть"):
                if hmac.compare_digest(entered.encode(), password.encode()):
                    st.session_state["authenticated"] = digest
                    st.rerun()
                else:
                    st.error("Пароль не подходит")
        st.stop()
    try:
        store = connect(secrets)
        data = store.load()
        if data.get("lease"):
            from datetime import datetime, timezone
            if datetime.fromisoformat(data["lease"]["until"]) <= datetime.now(timezone.utc):
                store.transact(recover_expired, "Ангелис: recover interrupted run")
                data = store.load()
    except Exception as error:
        st.error(str(error))
        st.stop()
    notice = st.session_state.pop("notice", "")
    if notice:
        st.success(notice)
    section = st.sidebar.radio("Офис", SECTIONS)
    totals = budget_totals(data)
    st.sidebar.caption(f"День: ${totals['daily']:.4f} / ${data['settings']['daily_budget']:.2f}")
    st.sidebar.caption("Ключ OpenAI задан; доступ проверяется API-тестом" if secrets.get("OPENAI_API_KEY") else "Ключ OpenAI ещё не задан")
    enabled = data["settings"]["scheduler_enabled"] and data["settings"]["autonomous_mode"]
    st.sidebar.write("Scheduler: **ON**" if enabled else "Scheduler: **OFF**")
    jobs = next_jobs(data)
    if jobs:
        st.sidebar.caption("Следующий плановый запуск: " + jobs[0]["at"][:16])
    if st.sidebar.button("Pause All Autonomous Work", use_container_width=True):
        perform(pause_all, store)
    if secrets["ANGELIS_STORAGE"] == "local":
        st.sidebar.caption("Локальное хранение · только для разработки")
    st.header(section)
    if section == "TODAY":
        today(data, store, secrets)
    elif section == "BACKLOG":
        backlog(data, store, secrets)
    elif section == "JOURNAL":
        journal(data)
    elif section == "COSTS":
        costs(data, store)
    elif section == "SETTINGS":
        settings(data, store)
    elif section == "STRATEGY":
        st.write("Текущая миссия: рост Viktor Mir как художника и живописца при сохранении татуировки как источника дохода.")
        st.subheader("Открытые вопросы")
        for question in data["state"]["active_questions"]:
            st.write(question)
        st.subheader("Гипотезы")
        for hypothesis in data["state"]["current_hypotheses"]:
            st.write(hypothesis)
        artifacts_view(data, {"strategy", "decision"})
    elif section == "RESEARCH":
        artifacts_view(data, {"research"})
    elif section == "CONTENT":
        st.caption("Концепции, серии, сценарии и черновики. Публикация остаётся за Виктором.")
        artifacts_view(data, {"editorial"})
    elif section == "ART":
        st.write("Живопись, авторский язык, каталожная структура и художественные проекты.")
        st.caption("Исходный каталог произведений пока не предоставлен. Это не доказательство выставок или продаж.")
        artifacts_view(data, {"archive", "strategy", "decision"})
    elif section == "TATTOO":
        st.write("Татуировка как текущий коммерческий двигатель и часть авторской практики.")
        artifacts_view(data, {"archive", "strategy", "editorial"})


main()
