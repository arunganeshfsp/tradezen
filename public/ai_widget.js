async function loadAISignal() {
    try {
        const res = await fetch("/api/ai-signal");
        const data = await res.json();

        const el = document.getElementById("ai-signal-box");
        if (!el) return;

        el.innerHTML = `
            <div style="padding:10px;border:1px solid #ccc;margin-top:10px;">
                <h3>NIFTY AI Signal</h3>
                <p><b>Signal:</b> ${data.signal || "N/A"}</p>
                <p><b>Confidence:</b> ${data.confidence || "-"}</p>
            </div>
        `;
    } catch (err) {
        console.error("AI fetch error:", err);
    }
}