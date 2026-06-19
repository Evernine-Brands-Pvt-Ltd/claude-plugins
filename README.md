# Evernine Claude Code plugins

Team-shared [Claude Code](https://code.claude.com) plugins. Add this marketplace once and the plugins below become available in every repo.

## Install

```
/plugin marketplace add Evernine-Brands-Pvt-Ltd/claude-plugins
/plugin install daily-progress@evernine
```

Or auto-enable for everyone by adding this to a shared `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "evernine": {
      "source": { "source": "github", "repo": "Evernine-Brands-Pvt-Ltd/claude-plugins" }
    }
  },
  "enabledPlugins": {
    "daily-progress@evernine": true
  }
}
```

## Plugins

| Plugin | What it does |
|---|---|
| `daily-progress` | End-of-day progress digest from the day's git commits + Claude session transcripts → 5-10 management-facing bullets + pace metric, saved locally and published to Notion. Invoke `/daily-progress`. |
