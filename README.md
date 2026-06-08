# List Merger for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA version](https://img.shields.io/badge/Home%20Assistant-2023.11%2B-blue.svg)](https://www.home-assistant.io)

Merge multiple Home Assistant **todo lists** into one master list — event-driven, no polling, fully configurable per source.

---

## How it works

List Merger listens for changes on your chosen todo lists in real time. When a new item appears on a source list it is automatically added to the master list. You control per source whether sync goes one way or both ways, and whether items should be removed from the source once they land on master.

```
todo.etilbudsavis_cart  ──(one-way, delete)──►┐
todo.mealie_shopping    ◄──(two-way)──────────►│  todo.Indkøbsliste  (master)
todo.low_stock_items    ──(one-way, delete)──►┘
```

---

## Features

| Feature | Details |
|---|---|
| **Per-source sync direction** | One-way (source → master) or two-way (source ↔ master), configured per list |
| **Delete on merge** | Optionally remove an item from the source list once it is added to master |
| **Duplicate handling** | Deduplicate by name (case-insensitive) — or keep all copies |
| **Completed item behaviour** | Sync completion back to source / mark complete on master only / delete from both |
| **New or existing master** | Create a fresh virtual todo list, or use an existing HA todo entity as master |
| **Persistent** | Items and sync state survive HA restarts |
| **Event-driven** | Reacts instantly to `state_changed` events — zero polling |

---

## Installation

### Via HACS (recommended)

1. Open **HACS → Integrations → ⋮ → Custom repositories**
2. Add URL: `https://github.com/CagosDk/hacs-ListMerger` — type: **Integration**
3. Search for **List Merger** and install
4. Restart Home Assistant

### Manual

Copy `custom_components/list_merger/` into your HA `config/custom_components/` folder and restart.

---

## Setup

1. Go to **Settings → Devices & Services → Add integration**
2. Search for **List Merger**
3. Follow the config flow:

| Step | What you configure |
|---|---|
| 1 | Merger name, master list type (new or existing), duplicate handling, completed-item behaviour |
| 2 *(if existing master)* | Select the existing todo entity to use as master |
| 3 | Select all source todo lists (multi-select) |
| 4+ | One screen per source: sync direction and delete-on-merge toggle |

Reconfigure at any time via the integration's **Configure** button.

---

## Example setup

**Goal:** One shared shopping list that pulls from eTilbudsavis deals, Mealie's meal planner, and a low-stock inventory tracker.

| Source list | Direction | Delete on merge |
|---|---|---|
| `todo.etilbudsavis_cart` | One-way → master | Yes — removes from eTilbudsavis after adding |
| `todo.mealie_shopping` | Two-way ↔ master | No — keeps Mealie in sync both ways |
| `todo.low_stock_items` | One-way → master | Yes — clears inventory alerts once captured |

Items added directly to the master list are automatically pushed back to all two-way sources (Mealie in this case).

---

## Configuration options

### Completed item behaviour

| Option | What happens when you check off an item on master |
|---|---|
| Sync back to source | The item is also marked complete on the source list |
| Master only | Only marked complete on master — source is untouched |
| Delete from both | Item is removed from master and from the source list |

### Duplicate handling

| Option | Behaviour |
|---|---|
| Deduplicate *(recommended)* | If "Mælk" already exists on master, it is not added again — but the new origin is still tracked so completion syncs correctly |
| Keep duplicates | Every occurrence from every source is added as a separate item |

---

## Requirements

- Home Assistant 2023.11 or newer
- HACS 1.x

---

## License

MIT
