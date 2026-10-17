# Frontend (React 19 + Vite)

Two UIs share this package:

- `src/studio/` — the desktop studio. Screens are registered once in
  `studio/navigation.ts` (rail and tabs) and `studio/StudioApp.tsx` (routes).
  Shared pieces live in `studio/components/` (Overlay, ScreenTabs, the
  notification bell) and `studio/pages/db/Database.tsx` / `forms.tsx`
  (tables, feedback, mutations).
- `src/mobile/` — the phone UI (quick entry, review, portfolio).

`src/api/` holds the HTTP clients; `src/types/` the shared types.

## Checks

```bash
npx tsc -b            # type check (tsc --noEmit checks nothing here)
npx eslint src/studio
```

## Conventions

- Loaders passed to `useResource` must be stable (module-level or
  `useCallback`). An inline loader reloads on every render, and the endless
  re-render keeps a route transition from ever committing.
- Notifications that need the user's attention come from the backend's
  notifications table (`api/notifications.ts`, `NotificationsProvider`); a new
  kind needs a generator on the backend, not a new frontend store.
