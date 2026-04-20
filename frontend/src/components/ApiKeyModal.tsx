/**
 * ApiKeyModal — prompt the user to enter their BOT_API_SECRET.
 *
 * Shown automatically when:
 *   - No key is stored in localStorage on first load
 *   - Any API request returns HTTP 403
 *
 * The entered key is saved to localStorage and injected into every subsequent
 * request via the axios interceptor in api/client.ts.
 */

import { useEffect, useRef, useState } from "react";
import { getApiKey, setApiKey } from "../api/client";
import styles from "./ApiKeyModal.module.css";

interface Props {
  onSaved: () => void;
}

export default function ApiKeyModal({ onSaved }: Props) {
  const [value, setValue] = useState(getApiKey());
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleSave() {
    const trimmed = value.trim();
    if (!trimmed) {
      setError("API key cannot be empty");
      return;
    }
    setApiKey(trimmed);
    onSaved();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSave();
    if (e.key === "Escape") {/* do nothing — key is required */}
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.icon}>🔑</div>
        <h2 className={styles.title}>API Key Required</h2>
        <p className={styles.desc}>
          Enter your <code>BOT_API_SECRET</code> to connect to the trading API.
          The key is stored in your browser only.
        </p>
        <input
          ref={inputRef}
          className={styles.input}
          type="password"
          placeholder="Paste your BOT_API_SECRET here…"
          value={value}
          onChange={(e) => { setValue(e.target.value); setError(""); }}
          onKeyDown={handleKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        {error && <p className={styles.error}>{error}</p>}
        <button className={styles.btn} onClick={handleSave}>
          Connect
        </button>
        <p className={styles.hint}>
          Generate a key on your server:&nbsp;
          <code>openssl rand -hex 32</code>
          <br />
          Then set it as <code>BOT_API_SECRET</code> in your <code>.env</code> file.
        </p>
      </div>
    </div>
  );
}
