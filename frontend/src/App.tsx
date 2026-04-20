import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Dashboard from "./pages/Dashboard";
import Backtests from "./pages/Backtests";
import Trades from "./pages/Trades";
import BotControl from "./pages/BotControl";
import Provider from "./pages/Provider";
import Wallet from "./pages/Wallet";
import Presets from "./pages/Presets";
import Market from "./pages/Market";
import Portfolio from "./pages/Portfolio";
import Settings from "./pages/Settings";
import StrategyEngine from "./pages/StrategyEngine";
import ApiKeyModal from "./components/ApiKeyModal";
import { useBotStatus } from "./hooks/useBotStatus";
import { fetchPortfolioStatus } from "./api/client";
import type { PortfolioStatus } from "./api/client";
import { getApiKey, clearApiKey } from "./api/client";
import styles from "./App.module.css";

const TABS = [
  { id: "dashboard",        label: "📊 Dashboard" },
  { id: "market",           label: "📡 Market" },
  { id: "strategy-engine",  label: "⚡ Strategy" },
  { id: "presets",          label: "🎛️ Presets" },
  { id: "backtests",        label: "🔬 Backtests" },
  { id: "trades",           label: "📋 Trades" },
  { id: "wallet",           label: "💰 Wallet" },
  { id: "bot",              label: "🤖 Bot" },
  { id: "portfolio",        label: "🗂 Portfolio" },
  { id: "provider",         label: "⚙️ Provider" },
  { id: "settings",         label: "🔧 Settings" },
] as const;

type Tab = (typeof TABS)[number]["id"];

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const { data: botStatus } = useBotStatus();
  const { data: portfolioStatus } = useQuery<PortfolioStatus>({
    queryKey: ["portfolioStatus"],
    queryFn:  fetchPortfolioStatus,
    refetchInterval: 5_000,
    retry: false,
  });

  // ── API key gate ──────────────────────────────────────────────────────────
  const [showKeyModal, setShowKeyModal] = useState(!getApiKey());

  useEffect(() => {
    // Listen for 403 responses emitted by the axios interceptor
    const handler = () => setShowKeyModal(true);
    window.addEventListener("bot:auth-error", handler);
    return () => window.removeEventListener("bot:auth-error", handler);
  }, []);

  function handleKeySaved() {
    setShowKeyModal(false);
    window.location.reload(); // re-run all queries with the new key
  }

  function handleDisconnect() {
    clearApiKey();
    setShowKeyModal(true);
  }

  return (
    <div className={styles.app}>
      {showKeyModal && <ApiKeyModal onSaved={handleKeySaved} />}

      <header className={styles.header}>
        <div className={styles.logo}>⚡ Crypto Bot</div>

        <nav className={styles.nav}>
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`${styles.navBtn} ${tab === t.id ? styles.active : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.id === "bot" && botStatus?.running && (
                <span className={styles.dot} />
              )}
              {t.id === "bot" && botStatus?.crashed && (
                <span className={styles.dotCrash} />
              )}
              {t.id === "portfolio" && portfolioStatus?.running && (
                <span className={styles.dot} />
              )}
              {t.id === "portfolio" && (portfolioStatus?.crashed_slots ?? 0) > 0 && (
                <span className={styles.dotCrash} />
              )}
            </button>
          ))}
        </nav>

        <div className={styles.headerRight}>
          <div className={styles.statusBadge}>
            {botStatus?.running ? (
              <span className={styles.live}>
                ● {botStatus.mode?.toUpperCase()} — {botStatus.strategy}
              </span>
            ) : botStatus?.crashed ? (
              <span className={styles.crashed}>⚠ CRASHED</span>
            ) : portfolioStatus?.running ? (
              <span className={styles.live}>
                ● PORTFOLIO — {portfolioStatus.alive_slots}/{portfolioStatus.total_slots} slots
              </span>
            ) : portfolioStatus?.crashed_slots ? (
              <span className={styles.crashed}>⚠ PORTFOLIO CRASH</span>
            ) : (
              <span className={styles.idle}>● IDLE</span>
            )}
          </div>

          {/* API key indicator — click to re-enter the key */}
          {!showKeyModal && (
            <button
              className={styles.keyBtn}
              title="Click to change API key"
              onClick={handleDisconnect}
            >
              🔑
            </button>
          )}
        </div>
      </header>

      <main className={styles.main}>
        {tab === "dashboard"       && <Dashboard />}
        {tab === "market"          && <Market />}
        {tab === "strategy-engine" && <StrategyEngine />}
        {tab === "presets"         && <Presets />}
        {tab === "backtests"       && <Backtests />}
        {tab === "trades"          && <Trades />}
        {tab === "wallet"          && <Wallet />}
        {tab === "bot"             && <BotControl />}
        {tab === "portfolio"       && <Portfolio />}
        {tab === "provider"        && <Provider />}
        {tab === "settings"        && <Settings />}
      </main>
    </div>
  );
}
