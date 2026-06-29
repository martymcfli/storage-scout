import streamlit as st
import requests

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Storage Scout",
    page_icon="🏭",
    layout="wide",
)

ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --- helpers ---

def api_get(path: str, silent: bool = False):
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        if not silent:
            st.error(f"API error: {e}")
        return None
    except Exception as e:
        if not silent:
            st.error(f"API error: {e}")
        return None


def api_post(path: str, data: dict, timeout: int = 120):
    try:
        r = requests.post(f"{API_BASE}{path}", json=data, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error: {e}")
        return None


def score_color(score: int) -> str:
    if score >= 8:
        return "🔴"
    elif score >= 6:
        return "🟡"
    elif score >= 4:
        return "🟢"
    return "⚪"


# --- first-run gate ---

root = api_get("/", silent=True) or {}
profile_configured = root.get("profile_configured", False)

if not profile_configured:
    st.warning("👋 Welcome to Storage Scout! Set up your Scout Profile before running discovery.")

page = st.sidebar.radio(
    "Navigation",
    ["Profile", "Dashboard", "Discover", "Auctions", "Scout AI"],
)

if not profile_configured and page != "Profile":
    st.info("Complete your profile setup first to enable auto-discovery.")
    st.stop()


# ============================================================
# PROFILE
# ============================================================

if page == "Profile":
    st.title("Scout Profile")
    st.caption("Tell Scout where you are and when you can attend auctions. Set it once — Scout handles the rest.")

    existing = api_get("/profile", silent=True)

    with st.form("profile_form"):
        col1, col2 = st.columns(2)

        with col1:
            home_zip = st.text_input(
                "Home ZIP code",
                value=existing["home_zip"] if existing else "",
                placeholder="e.g. 90210",
                help="Scout expands outward from here.",
            )
            max_miles = st.slider(
                "Max drive distance (miles)",
                min_value=10, max_value=150, step=5,
                value=existing["max_miles"] if existing else 50,
                help="Straight-line radius. A 50-mile radius covers ~70-90 ZIPs.",
            )
            budget_ceiling = st.number_input(
                "Max bid budget (optional, $)",
                min_value=0, max_value=50000, step=100,
                value=existing.get("budget_ceiling") or 0,
                help="Units likely to exceed this are flagged. 0 = no limit.",
            )

        with col2:
            available_days = st.multiselect(
                "Days you can attend auctions",
                options=ALL_DAYS,
                default=[d.capitalize() for d in (existing["available_days"] if existing else ["Saturday", "Sunday"])],
                help="Only units auctioned on these days will be processed. Units with unknown dates are always included.",
            )
            alert_score_threshold = st.slider(
                "Alert me when score is ≥",
                min_value=5, max_value=10,
                value=existing["alert_score_threshold"] if existing else 7,
                help="Units at or above this score get written to alerts.",
            )

        submitted = st.form_submit_button("Save Profile", type="primary", use_container_width=True)

    if submitted:
        if not home_zip or not home_zip.strip().isdigit() or len(home_zip.strip()) != 5:
            st.error("Please enter a valid 5-digit ZIP code.")
        elif not available_days:
            st.error("Select at least one available day.")
        else:
            payload = {
                "home_zip": home_zip.strip(),
                "max_miles": max_miles,
                "available_days": [d.lower() for d in available_days],
                "budget_ceiling": budget_ceiling if budget_ceiling > 0 else None,
                "alert_score_threshold": alert_score_threshold,
            }
            result = api_post("/profile", payload)
            if result:
                st.success("Profile saved!")
                st.rerun()

    # coverage card (shown once profile exists)
    if existing or profile_configured:
        st.divider()
        with st.spinner("Calculating coverage..."):
            coverage = api_get("/profile/coverage", silent=True)

        if coverage:
            loc = coverage.get("location") or {}
            city_state = f"{loc.get('city', '')}, {loc.get('state', '')}" if loc else coverage["home_zip"]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Home", city_state)
            c2.metric("Radius", f"{coverage['max_miles']} mi")
            c3.metric("ZIPs in range", coverage["zip_count"])
            c4.metric("Alert threshold", f"≥ {coverage['alert_score_threshold']}/10")

            st.info(
                f"Scout will search **{coverage['zip_count']} ZIP codes** within "
                f"**{coverage['max_miles']} miles** of {coverage['home_zip']}, "
                f"on **{', '.join(d.capitalize() for d in coverage['available_days']) or 'any day'}**."
            )


# ============================================================
# DASHBOARD
# ============================================================

elif page == "Dashboard":
    st.title("Dashboard")

    auctions = api_get("/auctions") or []
    alerts = api_get("/alerts") or []
    profile = api_get("/profile", silent=True)

    evaluated = [a for a in auctions if a.get("evaluation")]
    high_value = [a for a in evaluated if a["evaluation"]["score"] >= (profile["alert_score_threshold"] if profile else 7)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Units", len(auctions))
    c2.metric("Evaluated", len(evaluated))
    c3.metric("High Value", len(high_value))
    c4.metric("Alerts", len(alerts))

    if alerts:
        st.subheader("🚨 Alerts — Act On These")
        for alert in sorted(alerts, key=lambda a: a["score"], reverse=True):
            st.warning(
                f"**{alert['tenant_name']}** — Score {alert['score']}/10 — "
                f"{alert['trade_equipment_probability'].capitalize()} trade probability — "
                f"Est. {alert['estimated_value_range']}"
            )
        st.divider()

    if evaluated:
        st.subheader("All Evaluated Units")
        threshold = profile["alert_score_threshold"] if profile else 7
        for unit in sorted(evaluated, key=lambda u: u["evaluation"]["score"], reverse=True)[:15]:
            ev = unit["evaluation"]
            tenant = unit["tenant"]
            with st.expander(
                f"{score_color(ev['score'])} {tenant['name']} — Unit {tenant['unit_number']} — Score {ev['score']}/10"
            ):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.write(f"**Career identified:** {ev.get('career_identified', 'unknown')}")
                    st.write(f"**Facility:** {unit.get('facility_name', '')} {tenant.get('facility_address', '')}")
                    st.write(f"**Auction date:** {tenant.get('auction_date', 'unknown')}")
                    st.write(f"**Recommendation:** {ev['recommendation']}")
                    st.write(f"**Trade equipment:** {ev['trade_equipment_probability']}")
                    st.write(f"**Est. value:** {ev['estimated_value_range']}")
                with col_b:
                    st.write(f"**Likely contents:** {', '.join(ev['likely_contents'])}")
                    st.write(f"**Interest signals:** {', '.join(ev['interest_signals'])}")
                    st.write(f"**Reasoning:** {ev['reasoning']}")
    else:
        st.info("No evaluated units yet — run discovery from the Discover page.")


# ============================================================
# DISCOVER
# ============================================================

elif page == "Discover":
    st.title("Discover Auctions")

    profile = api_get("/profile", silent=True)
    coverage = api_get("/profile/coverage", silent=True)

    # --- Profile summary banner ---
    if profile and coverage:
        loc = coverage.get("location") or {}
        city_state = f"{loc.get('city', '')}, {loc.get('state', '')}" if loc else profile["home_zip"]
        days_str = ", ".join(d.capitalize() for d in profile["available_days"]) or "any day"
        st.success(
            f"**Profile active** — Searching {coverage['zip_count']} ZIPs within "
            f"{profile['max_miles']} miles of {city_state} · Available: {days_str}"
        )

    # --- Auto-discover from profile ---
    st.subheader("Auto-Discover (uses your profile)")
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Run Discovery", type="primary", use_container_width=True):
            with st.spinner(
                f"Searching {coverage['zip_count'] if coverage else '?'} ZIPs "
                f"and running the full pipeline on new finds..."
            ):
                result = api_post("/discover", {}, timeout=600)
            if result:
                st.success(
                    f"Searched **{result['new_urls_found']}** new URLs → "
                    f"added **{result['new_units_added']}** units"
                    + (f" (day filter active)" if result.get("day_filter_active") else "")
                )
                if result.get("errors"):
                    st.warning(f"{len(result['errors'])} URLs had errors during pipeline.")
    with col1:
        st.caption(
            "Scans StorageTreasures and Bid13, skips duplicates, "
            "filters by your available days, then scores every new unit automatically."
        )

    st.divider()

    # --- Manual URL scrape ---
    st.subheader("Scrape a Specific URL")
    url = st.text_input("Paste an auction notice URL", placeholder="https://www.storagetreasures.com/auctions/...")
    if st.button("Run Full Pipeline", disabled=not url):
        with st.spinner("Scraping, enriching, and evaluating..."):
            result = api_post("/scrape", {"url": url})
        if result:
            st.success(f"Found {result['units_found']} units.")
            for unit in result.get("units", []):
                ev = unit.get("evaluation", {})
                st.info(
                    f"**{unit['tenant']['name']}** — Unit {unit['tenant']['unit_number']} — "
                    f"Score {ev.get('score', '?')}/10 — {ev.get('recommendation', '')}"
                )

    st.divider()

    # --- ZIP override ---
    with st.expander("Override: search specific ZIP codes"):
        zip_input = st.text_input("ZIP codes (comma-separated)", placeholder="90210, 10001, 60601")
        if st.button("Discover These ZIPs", disabled=not zip_input):
            zips = [z.strip() for z in zip_input.split(",") if z.strip()]
            with st.spinner(f"Searching {len(zips)} ZIP(s)..."):
                result = api_post("/discover", {"zip_codes": zips}, timeout=600)
            if result:
                st.success(
                    f"Found {result['new_urls_found']} new URLs, "
                    f"added {result['new_units_added']} units."
                )


# ============================================================
# AUCTIONS
# ============================================================

elif page == "Auctions":
    st.title("All Auction Units")

    auctions = api_get("/auctions") or []
    profile = api_get("/profile", silent=True)
    threshold = profile["alert_score_threshold"] if profile else 7

    if not auctions:
        st.info("No auctions yet — run discovery from the Discover page.")
    else:
        col1, col2 = st.columns(2)
        min_score = col1.slider("Min score", 1, 10, 1)
        show_evaluated_only = col2.checkbox("Evaluated only")

        filtered = auctions
        if show_evaluated_only:
            filtered = [a for a in filtered if a.get("evaluation")]
        filtered = [
            a for a in filtered
            if not a.get("evaluation") or a["evaluation"]["score"] >= min_score
        ]

        st.caption(f"Showing {len(filtered)} of {len(auctions)} units")

        for unit in filtered:
            tenant = unit["tenant"]
            ev = unit.get("evaluation")
            score_str = f"Score {ev['score']}/10" if ev else "Not evaluated"

            with st.expander(f"{score_color(ev['score']) if ev else '⚪'} {tenant['name']} — Unit {tenant['unit_number']} — {score_str}"):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.write(f"**Facility:** {unit.get('facility_name', '')} {tenant.get('facility_address', '')}")
                    st.write(f"**Auction date:** {tenant.get('auction_date', 'unknown')}")
                    st.write(f"**Default owed:** {tenant.get('default_amount', 'unknown')}")
                    st.write(f"**Source:** {unit['source_url']}")

                    if not unit.get("enrichment"):
                        if st.button("Enrich", key=f"enrich_{unit['id']}"):
                            with st.spinner("Enriching..."):
                                api_post(f"/enrich/{unit['id']}", {})
                            st.rerun()
                    elif not ev:
                        if st.button("Evaluate", key=f"eval_{unit['id']}"):
                            with st.spinner("Evaluating..."):
                                api_post(f"/evaluate/{unit['id']}", {})
                            st.rerun()

                with col_b:
                    if ev:
                        st.write(f"**Score:** {score_color(ev['score'])} {ev['score']}/10")
                        st.write(f"**Career identified:** {ev.get('career_identified', 'unknown')}")
                        st.write(f"**Recommendation:** {ev['recommendation']}")
                        st.write(f"**Trade equipment:** {ev['trade_equipment_probability']}")
                        st.write(f"**Est. value:** {ev['estimated_value_range']}")
                        st.write(f"**Likely contents:** {', '.join(ev['likely_contents'])}")
                    en = unit.get("enrichment")
                    if en:
                        st.write(f"**Obituary found:** {en['obituary_found']}")
                        if en.get("obit_career_description"):
                            st.write(f"**Obit career:** {en['obit_career_description']}")
                        if en.get("high_value_trade_signals"):
                            st.write(f"**High-value trade signals:** {', '.join(en['high_value_trade_signals'])}")
                        elif en.get("trade_profession_signals"):
                            st.write(f"**Trade signals:** {', '.join(en['trade_profession_signals'])}")

                # Deep Research
                if ev:
                    st.divider()
                    dr_key = f"dr_{unit['id']}"
                    if st.button("Deep Research", key=dr_key, type="primary"):
                        dr_placeholder = st.empty()
                        full_dr = ""
                        dr_placeholder.markdown("*Running deep research — querying all specialists...*")
                        try:
                            with requests.post(
                                f"{API_BASE}/research/{unit['id']}",
                                stream=True, timeout=120,
                            ) as r:
                                for line in r.iter_lines():
                                    if line:
                                        decoded = line.decode("utf-8")
                                        if decoded.startswith("data: "):
                                            chunk = decoded[6:]
                                            if chunk == "[DONE]":
                                                break
                                            full_dr += chunk
                                            dr_placeholder.markdown(full_dr + "▌")
                        except Exception as e:
                            full_dr = f"Deep research error: {e}"
                        dr_placeholder.markdown(full_dr)

                if st.button("Delete", key=f"del_{unit['id']}", type="secondary"):
                    requests.delete(f"{API_BASE}/auctions/{unit['id']}")
                    st.rerun()


# ============================================================
# SCOUT AI
# ============================================================

elif page == "Scout AI":
    st.title("Scout AI")
    st.caption("Ask anything about storage auctions. Scout coordinates your specialist team.")

    auctions = api_get("/auctions") or []
    evaluated = [a for a in auctions if a.get("evaluation")]

    selected_id = None
    if evaluated:
        options = {
            f"{a['tenant']['name']} — Unit {a['tenant']['unit_number']} — Score {a['evaluation']['score']}/10": a["id"]
            for a in sorted(evaluated, key=lambda u: u["evaluation"]["score"], reverse=True)
        }
        choice = st.selectbox("Focus on a unit (optional):", ["— General —"] + list(options.keys()))
        if choice != "— General —":
            selected_id = options[choice]

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    st.caption("Tip: type `/deep-research` to run the full multi-agent cross-reference report with cost/benefit analysis.")
    user_input = st.chat_input("Ask anything — or type /deep-research for the full report...")

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            full_response = ""
            placeholder.markdown("▌")

            history_payload = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.chat_history[:-1]
            ]

            try:
                with requests.post(
                    f"{API_BASE}/chat",
                    json={"message": user_input, "history": history_payload, "auction_id": selected_id},
                    stream=True,
                    timeout=60,
                ) as r:
                    for line in r.iter_lines():
                        if line:
                            decoded = line.decode("utf-8")
                            if decoded.startswith("data: "):
                                chunk = decoded[6:]
                                if chunk == "[DONE]":
                                    break
                                full_response += chunk
                                placeholder.markdown(full_response + "▌")
            except Exception as e:
                full_response = f"Error connecting to Scout AI: {e}"

            placeholder.markdown(full_response)

        st.session_state.chat_history.append({"role": "assistant", "content": full_response})
