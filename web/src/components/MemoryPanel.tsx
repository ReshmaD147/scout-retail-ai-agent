import { useState } from "react";
import type { UseMemorySettingsResult } from "../hooks/useMemorySettings";

interface MemoryPanelProps {
  memory: UseMemorySettingsResult;
}

const QUICK_PREFERENCES = [
  { type: "preferred_store", label: "Preferred store", placeholder: "Maple Grove" },
  { type: "width", label: "Shoe width", placeholder: "Wide" },
  { type: "fulfillment_preference", label: "Fulfillment preference", placeholder: "Pickup" },
];

function labelFor(type: string): string {
  return QUICK_PREFERENCES.find((item) => item.type === type)?.label ?? type.replace(/_/g, " ");
}

export function MemoryPanel({ memory }: MemoryPanelProps): JSX.Element {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const submit = (type: string): void => {
    const value = (drafts[type] ?? "").trim();
    if (!value) return;
    void memory.save(type, value);
    setDrafts((previous) => ({ ...previous, [type]: "" }));
  };

  return (
    <section className="memory-panel" aria-label="Scout memory settings">
      <div className="memory-panel__header">
        <div>
          <h3>Scout memory</h3>
          <p>Saved preferences can gently personalize ranking, but never override price, inventory, policy, or authorization.</p>
        </div>
        <label className="memory-panel__toggle">
          <span>Use saved preferences</span>
          <input
            type="checkbox"
            checked={memory.memoryEnabled}
            onChange={(event) => void memory.setEnabled(event.currentTarget.checked)}
          />
        </label>
      </div>

      {memory.errorMessage && <p className="memory-panel__error">{memory.errorMessage}</p>}
      {memory.isLoading && <p className="memory-panel__status">Loading memory…</p>}

      <ul className="memory-panel__list">
        {memory.preferences.length === 0 && <li className="memory-panel__empty">No saved preferences yet.</li>}
        {memory.preferences.map((preference) => (
          <li key={preference.preference_id}>
            <div>
              <strong>{labelFor(preference.type)}</strong>
              <span>{preference.value}</span>
            </div>
            <button type="button" onClick={() => void memory.remove(preference.preference_id)}>Remove</button>
          </li>
        ))}
      </ul>

      <div className="memory-panel__quick-add" aria-label="Add memory preferences">
        {QUICK_PREFERENCES.map((item) => (
          <label key={item.type}>
            <span>{item.label}</span>
            <div>
              <input
                type="text"
                placeholder={item.placeholder}
                value={drafts[item.type] ?? ""}
                onChange={(event) => setDrafts((previous) => ({ ...previous, [item.type]: event.currentTarget.value }))}
                disabled={!memory.memoryEnabled}
              />
              <button type="button" onClick={() => submit(item.type)} disabled={!memory.memoryEnabled}>Add</button>
            </div>
          </label>
        ))}
      </div>

      <div className="memory-panel__actions">
        <button type="button" onClick={() => void memory.clearSession()}>Clear session shopping context</button>
        <button type="button" onClick={() => void memory.clearAll()}>Clear all remembered preferences</button>
      </div>
    </section>
  );
}
