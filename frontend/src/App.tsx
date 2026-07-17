import { AppProvider, useAppContext } from "./context/AppContext";
import { SessionExpiredBanner } from "./components/SessionExpiredBanner";
import { ClearSessionButton } from "./components/ClearSessionButton";
import { UploadView } from "./views/UploadView";
import { ExtractionSummary } from "./views/ExtractionSummary";
import { LineupEditorView } from "./views/LineupEditorView";
import { ResultView } from "./views/ResultView";
import { useSessionRestore } from "./hooks/useSessionRestore";
import { useInactivityTimer } from "./hooks/useInactivityTimer";

function AppContent() {
  const { state } = useAppContext();

  // Restore session on page load/refresh
  useSessionRestore();

  // Track inactivity and expire session after 30 minutes
  useInactivityTimer();

  const renderView = () => {
    switch (state.phase) {
      case "upload":
        return <UploadView />;
      case "extracted":
        return <ExtractionSummary />;
      case "editing":
      case "predicting":
        return <LineupEditorView />;
      case "result":
        return <ResultView />;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <SessionExpiredBanner />

      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">
            What If World Cup Manager
          </h1>
          <ClearSessionButton />
        </div>
      </header>

      <main className="max-w-7xl mx-auto py-8">
        {renderView()}
      </main>
    </div>
  );
}

function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}

export default App;
