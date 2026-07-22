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

  let iamToken = null;
  let iamTokenExpiry = 0; // Unix ms

  /** Attached log file content (null when no file is attached) */
  let attachedLogContent = null;
  let attachedLogName = null;

  const MAX_FILE_BYTES = 2 * 1024 * 1024; // 2 MB
  const CHUNK_CHARS    = 6000;             // ~1500 tokens per chunk

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
          <button id="chatbot-clear" aria-label="Clear chat" title="Clear chat">
            <svg viewBox="0 0 32 32" width="16" height="16" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 12h2v11h-2zm6 0h2v11h-2z"/><path d="M4 6v2h2l2 19a2 2 0 002 2h12a2 2 0 002-2l2-19h2V6zm5.88 21L8.06 8h15.88l-1.82 19zM12 4h8v2h-8z"/>
            </svg>
          </button>
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
          <!-- File chip shown when a log file is attached -->
          <div id="chatbot-file-chip">
            <span id="chatbot-file-name"></span>
            <button id="chatbot-file-remove" aria-label="Remove attached file" title="Remove file">✕</button>
          </div>
          <div id="chatbot-input-controls">
            <!-- Hidden native file picker -->
            <input type="file" id="chatbot-file-input" accept=".log,.txt,.json,.out,.csv" aria-label="Upload log file" tabindex="-1" />
            <button id="chatbot-upload" aria-label="Attach log file" title="Attach log file (.log .txt .json)">
              <svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" width="18" height="18" fill="currentColor">
                <path d="M28 18v8a2 2 0 01-2 2H6a2 2 0 01-2-2v-8h2v8h20v-8zM16 4l-6 6 1.41 1.41L15 7.83V22h2V7.83l3.59 3.58L22 10z"/>
              </svg>
            </button>
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

  function clearChat() {
    conversationHistory.length = 0;
    document.getElementById("chatbot-messages").innerHTML = "";
    appendAssistantMessage(
      "Hi! I'm your WatsonX assistant. Paste an error message or ask me anything about your infrastructure."
    );
  }

  // ── Log file upload ───────────────────────────────────────────────────────────

  function showFileChip(name) {
    document.getElementById("chatbot-file-name").textContent = name;
    document.getElementById("chatbot-file-chip").classList.add("visible");
    document.getElementById("chatbot-input").placeholder = "Ask a question about the log…";
  }

  function removeFile() {
    attachedLogContent = null;
    attachedLogName = null;
    document.getElementById("chatbot-file-chip").classList.remove("visible");
    document.getElementById("chatbot-file-input").value = "";
    document.getElementById("chatbot-input").placeholder = "Describe an error or ask a question…";
  }

  function handleFileSelect(file) {
    if (!file) return;

    if (file.size > MAX_FILE_BYTES) {
      appendAssistantMessage(
        `⚠️ File too large: **${file.name}** is ${(file.size / 1024).toFixed(0)} KB. Maximum allowed is 2 MB.`
      );
      document.getElementById("chatbot-file-input").value = "";
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      attachedLogContent = e.target.result;
      attachedLogName = file.name;
      const sizeKB = (file.size / 1024).toFixed(0);
      const chunks = Math.ceil(attachedLogContent.length / CHUNK_CHARS);
      const hint = chunks > 1
        ? `${sizeKB} KB · will be analysed in ${chunks} parts`
        : `${sizeKB} KB`;
      showFileChip(`${file.name}  (${hint})`);
      document.getElementById("chatbot-input").focus();
    };
    reader.readAsText(file);
  }

  // ── Minimal Markdown renderer ─────────────────────────────────────────────────

  /**
   * Renders a small safe subset of Markdown to HTML.
   * Handles: fenced code blocks, inline code, bold, italic, unordered lists, line breaks.
   * Gracefully handles incomplete tokens that arrive mid-stream (renders them as plain text).
   * Uses textContent for all user-supplied text to prevent XSS.
   */
  function renderMarkdown(text) {
    const fragment = document.createDocumentFragment();

    // Split on complete fenced code blocks (```...```)
    // Also detect an unclosed opening ``` so it isn't silently dropped during streaming.
    const FENCE = "```";
    const parts = [];
    let remaining = text;

    while (remaining.length > 0) {
      const openIdx = remaining.indexOf(FENCE);
      if (openIdx === -1) {
        // No fence at all — plain text section
        parts.push({ type: "text", content: remaining });
        remaining = "";
      } else {
        // Text before the fence
        if (openIdx > 0) parts.push({ type: "text", content: remaining.slice(0, openIdx) });
        const afterOpen = remaining.slice(openIdx + 3);
        const closeIdx = afterOpen.indexOf(FENCE);
        if (closeIdx === -1) {
          // Unclosed fence — rest of text is an in-progress code block
          parts.push({ type: "code", content: afterOpen, open: true });
          remaining = "";
        } else {
          // Complete fenced block
          parts.push({ type: "code", content: afterOpen.slice(0, closeIdx), open: false });
          remaining = afterOpen.slice(closeIdx + 3);
        }
      }
    }

    parts.forEach(({ type, content, open }) => {
      if (type === "code") {
        // Strip optional language hint on the first line (e.g. ```python\n...)
        const body = content.replace(/^\w*\n/, "");
        const pre = document.createElement("pre");
        const codeEl = document.createElement("code");
        codeEl.textContent = open ? body + "▌" : body; // cursor hint while streaming
        pre.appendChild(codeEl);
        if (open) pre.style.opacity = "0.75"; // visually signal it's still arriving
        fragment.appendChild(pre);
        return;
      }

      // Process inline content line by line
      const lines = content.split("\n");
      lines.forEach((line, idx) => {
        const trimmed = line.trimStart();

        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          // Unordered list item
          const li = document.createElement("li");
          appendInline(li, trimmed.slice(2));
          fragment.appendChild(li);
        } else if (trimmed === "") {
          // Blank line — paragraph break
          if (idx > 0) fragment.appendChild(document.createElement("br"));
        } else {
          // Regular paragraph line
          const span = document.createElement("span");
          appendInline(span, line);
          fragment.appendChild(span);
          fragment.appendChild(document.createElement("br"));
        }
      });
    });

    return fragment;
  }

  /**
   * Parses inline markdown (bold, italic, inline code) into child nodes of `parent`.
   * Incomplete tokens at the end (e.g. opening ** without closing **) are rendered as
   * plain text so they are never silently dropped during streaming.
   */
  function appendInline(parent, text) {
    // Only match COMPLETE tokens — incomplete ones fall through to plain text
    const tokenRe = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
    let last = 0;
    let match;

    while ((match = tokenRe.exec(text)) !== null) {
      if (match.index > last) {
        parent.appendChild(document.createTextNode(text.slice(last, match.index)));
      }
      const token = match[0];
      if (token.startsWith("`")) {
        const code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        parent.appendChild(code);
      } else if (token.startsWith("**")) {
        const strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        parent.appendChild(strong);
      } else {
        const em = document.createElement("em");
        em.textContent = token.slice(1, -1);
        parent.appendChild(em);
      }
      last = match.index + token.length;
    }

    // Remainder — may include incomplete tokens like opening ** mid-stream; render as-is
    if (last < text.length) {
      parent.appendChild(document.createTextNode(text.slice(last)));
    }
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

    if (role === "assistant") {
      bubble.appendChild(renderMarkdown(text));
    } else {
      bubble.textContent = text;
    }

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
          max_new_tokens: 2048,
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
          streamBubble.innerHTML = "";
          streamBubble.appendChild(renderMarkdown(accumulated));
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
    if (!text && !attachedLogContent) return;

    // ── If a log file is attached, use chunked analysis ──────────────────────────
    if (attachedLogContent) {
      const logContent  = attachedLogContent;
      const logName     = attachedLogName;
      const userPrompt  = text || "Analyse this log and summarise any errors or issues.";
      const displayText = text
        ? `📎 **${logName}** — ${text}`
        : `📎 **${logName}** — Analyse this log`;

      removeFile();
      inputEl.value = "";
      autoResizeTextarea(inputEl);
      sendBtn.disabled = true;

      appendMessage("user", displayText);

      // Split log into chunks
      const chunks = [];
      for (let i = 0; i < logContent.length; i += CHUNK_CHARS) {
        chunks.push(logContent.slice(i, i + CHUNK_CHARS));
      }
      const total = chunks.length;

      try {
        if (total === 1) {
          // Single chunk — send directly as one user message
          conversationHistory.push({
            role: "user",
            content:
              `Log file: "${logName}"\n\nLog contents:\n\`\`\`\n${chunks[0]}\n\`\`\`\n\nUser question: ${userPrompt}`,
          });
        } else {
          // Multi-chunk: feed each chunk silently, then ask the question
          for (let i = 0; i < total; i++) {
            const partMsg = `Log file: "${logName}" — part ${i + 1} of ${total}:\n\`\`\`\n${chunks[i]}\n\`\`\``;
            conversationHistory.push({ role: "user", content: partMsg });

            // Show a progress bubble
            appendAssistantMessage(`📄 Ingesting **${logName}** — part ${i + 1} / ${total}…`);

            // Acknowledge each chunk (cheap call, no streaming needed for ack)
            conversationHistory.push({
              role: "assistant",
              content: `Received part ${i + 1} of ${total}. Continue.`,
            });
          }
          // Final turn: ask the actual question
          conversationHistory.push({ role: "user", content: `User question about the log above: ${userPrompt}` });
        }

        // Stream the final answer
        const msgList = document.getElementById("chatbot-messages");
        const wrapper  = document.createElement("div");
        wrapper.className = "chat-msg assistant";
        const label    = document.createElement("div");
        label.className = "msg-label";
        label.textContent = "WatsonX";
        const bubble   = document.createElement("div");
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
        appendAssistantMessage(
          `⚠️ Error: ${err.message || "Could not reach WatsonX. Check your API key and network."}`
        );
        console.error("[chatbot]", err);
      } finally {
        sendBtn.disabled = false;
        inputEl.focus();
      }
      return;
    }

    // ── Normal text-only message ──────────────────────────────────────────────────
    const userContent = text;
    appendMessage("user", userContent);
    conversationHistory.push({ role: "user", content: userContent });
    inputEl.value = "";
    autoResizeTextarea(inputEl);

    sendBtn.disabled = true;
    appendTypingIndicator();

    try {
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
    document.getElementById("chatbot-clear").addEventListener("click", clearChat);
    document.getElementById("chatbot-close").addEventListener("click", closePanel);

    // File upload
    document.getElementById("chatbot-upload").addEventListener("click", () => {
      document.getElementById("chatbot-file-input").click();
    });
    document.getElementById("chatbot-file-input").addEventListener("change", (e) => {
      handleFileSelect(e.target.files[0]);
    });
    document.getElementById("chatbot-file-remove").addEventListener("click", removeFile);

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
