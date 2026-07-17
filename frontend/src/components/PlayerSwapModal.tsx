import { useState, useCallback, useEffect, useRef, type FormEvent } from "react";
import type { Player } from "../types";

type Position = "GK" | "DEF" | "MID" | "FWD";

interface PlayerSwapModalProps {
  currentPlayer: Player;
  substitutes: Player[];
  onSwap: (newPlayer: Player) => void;
  onCancel: () => void;
}

export function PlayerSwapModal({
  currentPlayer,
  substitutes,
  onSwap,
  onCancel,
}: PlayerSwapModalProps) {
  const [mode, setMode] = useState<"substitute" | "custom">("substitute");
  const [selectedSubstitute, setSelectedSubstitute] = useState<Player | null>(null);
  const [customName, setCustomName] = useState("");
  const [customPosition, setCustomPosition] = useState<Position>("FWD");
  const [validationError, setValidationError] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFocusRef = useRef<HTMLButtonElement>(null);

  // Focus trap and escape key handling
  useEffect(() => {
    firstFocusRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
        return;
      }

      if (e.key === "Tab" && dialogRef.current) {
        const focusableElements = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey && document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        } else if (!e.shiftKey && document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  const handleSwap = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      setValidationError(null);

      if (mode === "substitute") {
        if (!selectedSubstitute) {
          setValidationError("Please select a substitute player.");
          return;
        }
        onSwap(selectedSubstitute);
      } else {
        const trimmedName = customName.trim();
        if (trimmedName.length < 1 || trimmedName.length > 100) {
          setValidationError("Player name must be between 1 and 100 characters.");
          return;
        }
        onSwap({
          name: trimmedName,
          squadNumber: currentPlayer.squadNumber,
          position: customPosition,
        });
      }
    },
    [mode, selectedSubstitute, customName, customPosition, currentPlayer, onSwap]
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="swap-modal-title"
      onClick={onCancel}
    >
      <div
        ref={dialogRef}
        className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="swap-modal-title" className="text-lg font-semibold text-gray-800 mb-1">
          Swap Player
        </h2>
        <p className="text-sm text-gray-600 mb-4">
          Replacing:{" "}
          <span className="font-medium">
            #{currentPlayer.squadNumber} {currentPlayer.name} ({currentPlayer.position})
          </span>
        </p>

        {/* Mode tabs */}
        <div className="flex gap-2 mb-4">
          <button
            ref={mode === "substitute" ? firstFocusRef : undefined}
            type="button"
            className={`flex-1 py-2 px-3 text-sm font-medium rounded-md transition-colors ${
              mode === "substitute"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
            onClick={() => setMode("substitute")}
            aria-pressed={mode === "substitute"}
          >
            Substitutes
          </button>
          <button
            ref={mode === "custom" ? firstFocusRef : undefined}
            type="button"
            className={`flex-1 py-2 px-3 text-sm font-medium rounded-md transition-colors ${
              mode === "custom"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
            onClick={() => setMode("custom")}
            aria-pressed={mode === "custom"}
          >
            Custom Player
          </button>
        </div>

        <form onSubmit={handleSwap}>
          {mode === "substitute" ? (
            <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-md">
              {substitutes.length === 0 ? (
                <p className="p-3 text-sm text-gray-500">No substitutes available.</p>
              ) : (
                <ul role="listbox" aria-label="Available substitutes">
                  {substitutes.map((sub) => (
                    <li key={`${sub.squadNumber}-${sub.name}`}>
                      <button
                        type="button"
                        role="option"
                        aria-selected={selectedSubstitute?.name === sub.name && selectedSubstitute?.squadNumber === sub.squadNumber}
                        className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                          selectedSubstitute?.name === sub.name &&
                          selectedSubstitute?.squadNumber === sub.squadNumber
                            ? "bg-blue-50 text-blue-800"
                            : "hover:bg-gray-50 text-gray-700"
                        }`}
                        onClick={() => {
                          setSelectedSubstitute(sub);
                          setValidationError(null);
                        }}
                      >
                        <span className="font-medium">#{sub.squadNumber}</span>{" "}
                        {sub.name}{" "}
                        <span className="text-gray-500">({sub.position})</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <label htmlFor="custom-player-name" className="block text-sm font-medium text-gray-700 mb-1">
                  Player Name
                </label>
                <input
                  id="custom-player-name"
                  type="text"
                  value={customName}
                  onChange={(e) => {
                    setCustomName(e.target.value);
                    setValidationError(null);
                  }}
                  maxLength={100}
                  placeholder="Enter player name"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              <div>
                <label htmlFor="custom-player-position" className="block text-sm font-medium text-gray-700 mb-1">
                  Position
                </label>
                <select
                  id="custom-player-position"
                  value={customPosition}
                  onChange={(e) => setCustomPosition(e.target.value as Position)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="GK">GK</option>
                  <option value="DEF">DEF</option>
                  <option value="MID">MID</option>
                  <option value="FWD">FWD</option>
                </select>
              </div>
            </div>
          )}

          {validationError && (
            <p role="alert" className="mt-3 text-sm text-red-600">
              {validationError}
            </p>
          )}

          <div className="flex gap-3 mt-5">
            <button
              type="submit"
              className="flex-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              Swap
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="flex-1 rounded-md bg-gray-100 px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
