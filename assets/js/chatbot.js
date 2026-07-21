/**
 * chatbot.js — WatsonX floating chatbot
 *
 * Depends on:  assets/js/config.js  (WATSONX_CONFIG must be loaded first)
 * Styles:      assets/css/chatbot.css
 *
 * Flow:
 *  1. User opens the panel and types a question / error message.
 *  2. An IBM Cloud IAM bearer token is obtained via the public token endpoint
 *     (token is cached for ~55 min to avoid redundant round-trips).
 *  3. The full conversation history is sent to the watsonx.ai /text/chat
 *     REST endpoint so the model can maintain context across turns.
 *  4. The assistant response is streamed back token-by-token and rendered
 *     progressively in the chat panel.
 */

(function () {
  "use strict";

  // ── Constants ────────────────────────────────────────────────────────────────

  // When WATSONX_CONFIG.PROXY is true (set by proxy.py), use local proxy
  // endpoints to avoid CORS restrictions on IBM Cloud APIs.
  const IAM_TOKEN_URL = "/proxy/iam-token";

  const SYSTEM_PROMPT =
    "You are an expert IBM Cloud and infrastructure assistant embedded in the " +
    "PowerVS Datacenter Status Dashboard. Help the user understand, diagnose, " +
    "and resolve infrastructure errors. Be concise and technical.";

  // ── State ─────────────────────────────────────────────────────────────────────

  /** @type {{ role: string; content: string }[]} */
  const conversationHistory = [];

  /** @type {Array|null} cached dashboard runs data */
  let dashboardData = null;

  // ── Dashboard data loader ─────────────────────────────────────────────────────

  async function loadDashboardData() {
    if (dashboardData !== null) return dashboardData;
    try {
      const resp = await fetch("../data/dc_scheduled_runs.json");
      if (!resp.ok) return [];
      dashboardData = await resp.json();
      return dashboardData;
    } catch {
      return [];
    }
  }

  function extractDateFromHtml(dateHtml) {
    // Dates are stored as <a href="...">2026-06-22</a>
    const match = String(dateHtml).match(/(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : null;
  }

  function buildDashboardContext(runs, days) {
    const now = new Date();
    const cutoff = new Date(now);
    cutoff.setDate(now.getDate() - days);

    const filtered = runs.filter(run => {
      const d = extractDateFromHtml(run.Date);
      return d && new Date(d) >= cutoff;
    });

    if (filtered.length === 0) {
      return `No runs found in the last ${days} days.`;
    }

    const lines = [`Dashboard data — last ${days} days (${filtered.length} runs):\n`];
    filtered.forEach(run => {
      const date = extractDateFromHtml(run.Date) || run.Date;
      const errorCount = run.Error?.errorCount ?? 0;
      const categories = run.Error?.categories?.join(", ") || "none";
      lines.push(`- [${date}] DC: ${run.DC} | OS: ${run.OS} | Repo: ${run.Repo} | Errors: ${errorCount} (${categories})`);
    });
    return lines.join("\n");
  }

  function detectDaysRequested(text) {
    // Detect "last N days/hours/weeks" in user message
    const match = text.match(/last\s+(\d+)\s*(day|days|week|weeks)/i);
    if (match) {
      const n = parseInt(match[1]);
      const unit = match[2].toLowerCase();
      return unit.startsWith("week") ? n * 7 : n;
    }
    // Default context window for data-related questions
    const dataKeywords = ["error", "fail", "run", "dc", "datacenter", "list", "show", "summary", "recent", "latest"];
    if (dataKeywords.some(k => text.toLowerCase().includes(k))) return 7;
    return 0;
  }

  let iamToken = null;
  let iamTokenExpiry = 0; // Unix ms

  // ── DOM helpers ───────────────────────────────────────────────────────────────

  function injectHTML() {
    const container = document.createElement("div");
    container.id = "chatbot-root";
    container.innerHTML = `
      <!-- Floating trigger bubble -->
      <button id="chatbot-bubble" aria-label="Open WatsonX assistant" title="Ask WatsonX">
        <!-- Chat speech-bubble icon (inline SVG, no external dependency) -->
        <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M16 4C9.4 4 4 8.9 4 15c0 3.1 1.3 5.9 3.4 8L6 28l5.3-1.4C12.8 27.2 14.4 27.5 16 27.5
                   c6.6 0 12-4.9 12-11S22.6 4 16 4zm0 20c-1.4 0-2.8-.3-4-.8l-.3-.1-3.1.8.8-3-.2-.3
                   C7.7 19.4 6.5 17.3 6.5 15 6.5 10.3 10.7 6.5 16 6.5S25.5 10.3 25.5 15 21.3 24 16 24z"/>
        </svg>
        <span class="bubble-badge" id="chatbot-badge"></span>
      </button>

      <!-- Chat panel -->
      <div id="chatbot-panel" role="dialog" aria-modal="true" aria-label="WatsonX assistant">

        <!-- Header -->
        <div id="chatbot-header">
          <div>
            <div class="chatbot-title">WatsonX Assistant</div>
            <div class="chatbot-subtitle">Powered by IBM watsonx.ai</div>
          </div>
          <button id="chatbot-close" aria-label="Close assistant">
            <svg viewBox="0 0 32 32" width="16" height="16" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
              <path d="M17.41 16l8.29-8.29-1.41-1.41L16 14.59 7.71 6.3 6.3 7.71 14.59 16 6.3 24.29l1.41 1.41L16 17.41l8.29 8.29 1.41-1.41z"/>
            </svg>
          </button>
        </div>

        <!-- Messages -->
        <div id="chatbot-messages" aria-live="polite" aria-relevant="additions"></div>

        <!-- Input row -->
        <div id="chatbot-input-row">
          <textarea
            id="chatbot-input"
            rows="1"
            placeholder="Describe an error or ask a question…"
            aria-label="Chat input"
          ></textarea>
          <button id="chatbot-send" aria-label="Send message">
            <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M27.45 15.11l-22-11a1 1 0 00-1.08.12 1 1 0 00-.27 1L7 16 4.1 26.77A1 1 0 005 28a1 1 0 00.45-.11l22-11a1 1 0 000-1.78zM6.2 25.37L8.6 16.8H18v-1.6H8.6L6.2 6.63 24.76 16z"/>
            </svg>
          </button>
        </div>

      </div>
    `;
    document.body.appendChild(container);
  }

  // ── Panel open / close ────────────────────────────────────────────────────────

  function openPanel() {
    document.getElementById("chatbot-panel").classList.add("open");
    document.getElementById("chatbot-badge").style.display = "none";
    document.getElementById("chatbot-input").focus();

    if (conversationHistory.length === 0) {
      appendAssistantMessage(
        "Hi! I'm your WatsonX assistant. Paste an error message or ask me anything about your infrastructure."
      );
    }
  }

  function closePanel() {
    document.getElementById("chatbot-panel").classList.remove("open");
  }

  // ── Message rendering ─────────────────────────────────────────────────────────

  function appendMessage(role, text) {
    const msgList = document.getElementById("chatbot-messages");

    const wrapper = document.createElement("div");
    wrapper.className = `chat-msg ${role}`;

    const label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = role === "user" ? "You" : "WatsonX";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    msgList.appendChild(wrapper);
    msgList.scrollTop = msgList.scrollHeight;

    return bubble; // caller can update content for streaming
  }

  function appendAssistantMessage(text) {
    appendMessage("assistant", text);
  }

  function appendTypingIndicator() {
    const msgList = document.getElementById("chatbot-messages");

    const wrapper = document.createElement("div");
    wrapper.className = "chat-msg assistant";
    wrapper.id = "chatbot-typing";

    const label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = "WatsonX";

    const bubble = document.createElement("div");
    bubble.className = "bubble typing";
    bubble.innerHTML = "<span></span><span></span><span></span>";

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    msgList.appendChild(wrapper);
    msgList.scrollTop = msgList.scrollHeight;
  }

  function removeTypingIndicator() {
    const el = document.getElementById("chatbot-typing");
    if (el) el.remove();
  }

  // ── IAM token ─────────────────────────────────────────────────────────────────

  async function getIamToken() {
    const now = Date.now();
    if (iamToken && now < iamTokenExpiry) return iamToken;

    const resp = await fetch(IAM_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "urn:ibm:params:oauth:grant-type:apikey",
        apikey: WATSONX_CONFIG.API_KEY,
      }),
    });

    if (!resp.ok) {
      const err = await resp.text();
      throw new Error(`IAM token request failed (${resp.status}): ${err}`);
    }

    const data = await resp.json();
    iamToken = data.access_token;
    // IBM IAM tokens are valid for 1 hour; refresh 5 min early
    iamTokenExpiry = now + (data.expires_in - 300) * 1000;
    return iamToken;
  }

  // ── WatsonX chat API call ─────────────────────────────────────────────────────

  /**
   * Send the full conversation to watsonx.ai /ml/v1/text/chat and stream the
   * response back, updating `streamBubble` progressively.
   *
   * @param {HTMLElement} streamBubble  - DOM element to stream text into
   */
  async function callWatsonX(streamBubble) {
    const token = await getIamToken();
    const endpoint = WATSONX_CONFIG.PROXY
      ? "/proxy/watsonx"
      : `${WATSONX_CONFIG.URL}/ml/v1/text/chat?version=2024-05-01`;

    const messages = [
      { role: "system", content: SYSTEM_PROMPT },
      ...conversationHistory,
    ];

    const resp = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        model_id: WATSONX_CONFIG.MODEL_ID,
        project_id: WATSONX_CONFIG.PROJECT_ID,
        messages,
        parameters: {
          max_new_tokens: 1024,
          temperature: 0.3,
        },
        stream: true,
      }),
    });

    if (!resp.ok) {
      const errBody = await resp.text();
      throw new Error(`watsonx API error (${resp.status}): ${errBody}`);
    }

    // ── Stream handling (server-sent events) ──────────────────────────────────
    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let accumulated = "";
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE lines are separated by "\n\n"
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep any incomplete line

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed === "data: [DONE]") continue;

        const jsonStr = trimmed.startsWith("data: ")
          ? trimmed.slice(6)
          : trimmed;

        let parsed;
        try {
          parsed = JSON.parse(jsonStr);
        } catch {
          continue; // skip non-JSON lines
        }

        const delta =
          parsed?.choices?.[0]?.delta?.content ??
          parsed?.results?.[0]?.generated_text ??
          "";

        if (delta) {
          accumulated += delta;
          streamBubble.textContent = accumulated;
          document.getElementById("chatbot-messages").scrollTop =
            document.getElementById("chatbot-messages").scrollHeight;
        }
      }
    }

    return accumulated;
  }

  // ── Send message handler ──────────────────────────────────────────────────────

  async function handleSend() {
    const inputEl = document.getElementById("chatbot-input");
    const sendBtn = document.getElementById("chatbot-send");
    const text = inputEl.value.trim();
    if (!text) return;

    // Render user message
    appendMessage("user", text);
    inputEl.value = "";
    autoResizeTextarea(inputEl);

    // Enrich message with dashboard data if the question is data-related
    const days = detectDaysRequested(text);
    let enrichedContent = text;
    if (days > 0) {
      const runs = await loadDashboardData();
      if (runs.length > 0) {
        const context = buildDashboardContext(runs, days);
        enrichedContent = `${text}\n\n[Dashboard context]\n${context}`;
      }
    }
    conversationHistory.push({ role: "user", content: enrichedContent });

    sendBtn.disabled = true;
    appendTypingIndicator();

    try {
      // Insert placeholder assistant bubble for streaming
      removeTypingIndicator();
      const msgList = document.getElementById("chatbot-messages");
      const wrapper = document.createElement("div");
      wrapper.className = "chat-msg assistant";

      const label = document.createElement("div");
      label.className = "msg-label";
      label.textContent = "WatsonX";

      const bubble = document.createElement("div");
      bubble.className = "bubble";

      wrapper.appendChild(label);
      wrapper.appendChild(bubble);
      msgList.appendChild(wrapper);
      msgList.scrollTop = msgList.scrollHeight;

      const fullReply = await callWatsonX(bubble);

      if (!fullReply) {
        bubble.textContent = "(No response received — please try again.)";
      }

      conversationHistory.push({ role: "assistant", content: fullReply });
    } catch (err) {
      removeTypingIndicator();
      appendAssistantMessage(
        `⚠️ Error: ${err.message || "Could not reach WatsonX. Check your API key and network."}`
      );
      console.error("[chatbot]", err);
    } finally {
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  // ── Textarea auto-resize ──────────────────────────────────────────────────────

  function autoResizeTextarea(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 100) + "px";
  }

  // ── Event wiring ──────────────────────────────────────────────────────────────

  function bindEvents() {
    document.getElementById("chatbot-bubble").addEventListener("click", openPanel);
    document.getElementById("chatbot-close").addEventListener("click", closePanel);

    const input = document.getElementById("chatbot-input");
    input.addEventListener("input", () => autoResizeTextarea(input));
    input.addEventListener("keydown", (e) => {
      // Send on Enter (without Shift)
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });

    document.getElementById("chatbot-send").addEventListener("click", handleSend);

    // Close panel when clicking outside
    document.addEventListener("click", (e) => {
      const panel = document.getElementById("chatbot-panel");
      const bubble = document.getElementById("chatbot-bubble");
      if (
        panel.classList.contains("open") &&
        !panel.contains(e.target) &&
        !bubble.contains(e.target)
      ) {
        closePanel();
      }
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────────

  function init() {
    if (typeof WATSONX_CONFIG === "undefined") {
      console.warn(
        "[chatbot] WATSONX_CONFIG not found. " +
        "Make sure assets/js/config.js is loaded before chatbot.js."
      );
      return;
    }

    injectHTML();
    bindEvents();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
