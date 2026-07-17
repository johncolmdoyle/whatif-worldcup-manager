import { useState, useCallback } from "react";
import type { Player } from "../types";
import { PlayerSwapModal } from "./PlayerSwapModal";

interface TeamLineupProps {
  teamName: string;
  lineup: Player[];
  originalLineup: Player[];
  substitutes: Player[];
  onPlayerSwap: (index: number, newPlayer: Player) => void;
}

function isPlayerChanged(current: Player, original: Player): boolean {
  return (
    current.name !== original.name ||
    current.squadNumber !== original.squadNumber ||
    current.position !== original.position
  );
}

export function TeamLineup({
  teamName,
  lineup,
  originalLineup,
  substitutes,
  onPlayerSwap,
}: TeamLineupProps) {
  const [swapIndex, setSwapIndex] = useState<number | null>(null);

  const handlePlayerClick = useCallback((index: number) => {
    setSwapIndex(index);
  }, []);

  const handleSwap = useCallback(
    (newPlayer: Player) => {
      if (swapIndex !== null) {
        onPlayerSwap(swapIndex, newPlayer);
        setSwapIndex(null);
      }
    },
    [swapIndex, onPlayerSwap]
  );

  const handleCancel = useCallback(() => {
    setSwapIndex(null);
  }, []);

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold text-gray-800 mb-3">{teamName}</h3>
      <ul aria-label={`${teamName} starting lineup`} className="space-y-1">
        {lineup.map((player, index) => {
          const changed = isPlayerChanged(player, originalLineup[index]);
          return (
            <li key={index}>
              <button
                type="button"
                onClick={() => handlePlayerClick(index)}
                aria-label={`Swap ${player.name}, number ${player.squadNumber}, position ${player.position}${changed ? ", modified" : ""}`}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  changed ? "border-l-4 border-blue-500 bg-blue-50" : "border-l-4 border-transparent"
                }`}
              >
                <span className="inline-block w-8 font-mono text-gray-500">
                  #{player.squadNumber}
                </span>
                <span className="font-medium text-gray-800">{player.name}</span>
                <span className="ml-2 text-xs text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                  {player.position}
                </span>
                {changed && (
                  <span className="ml-2 text-xs text-blue-600 font-medium" aria-hidden="true">
                    modified
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {swapIndex !== null && (
        <PlayerSwapModal
          currentPlayer={lineup[swapIndex]}
          substitutes={substitutes}
          onSwap={handleSwap}
          onCancel={handleCancel}
        />
      )}
    </div>
  );
}
