import React from "react";

import type { ChainPhaseArtifacts } from "@/lib/types";

interface ChainRelatedArtifactsPanelProps {
  phaseArtifacts: ChainPhaseArtifacts;
  focusPhase?: string;
  focusArtifactId?: string;
}

export function ChainRelatedArtifactsPanel({
  phaseArtifacts,
  focusPhase,
  focusArtifactId,
}: ChainRelatedArtifactsPanelProps) {
  const sections = Object.entries(phaseArtifacts).filter(([, items]) => items.length > 0);

  if (sections.length === 0) {
    return null;
  }

  return React.createElement(
    "div",
    { className: "grid grid-cols-1 gap-4 lg:grid-cols-3" },
    ...sections.map(([phase, items]) =>
      React.createElement(
        "div",
        {
          key: phase,
          className: `rounded-xl border p-4 ${
            focusPhase === phase
              ? "border-indigo-300 bg-indigo-50/40"
              : "border-gray-200 bg-white"
          }`,
        },
        React.createElement(
          "div",
          { className: "mb-2 flex items-center justify-between" },
          React.createElement(
            "h3",
            { className: "text-sm font-semibold text-gray-900" },
            phase,
          ),
          React.createElement(
            "span",
            { className: "text-xs text-gray-500" },
            "最近关联产物",
          ),
        ),
        React.createElement(
          "div",
          { className: "space-y-2" },
          ...items.map((item) =>
            React.createElement(
              "a",
              {
                key: item.artifactId,
                href: item.feedHref,
                className: `block rounded-lg border px-3 py-2 text-sm hover:bg-gray-50 ${
                  focusArtifactId === item.artifactId
                    ? "border-indigo-300 bg-white text-indigo-700"
                    : "border-gray-200 text-gray-700"
                }`,
              },
              React.createElement(
                "div",
                { className: "font-medium" },
                item.title,
              ),
              React.createElement(
                "div",
                { className: "text-xs text-gray-500" },
                item.artifactId,
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
