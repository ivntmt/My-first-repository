#!/usr/bin/env bash
# Status line: model + context-window usage ("limit") for this chat.
input=$(cat)
model=$(printf '%s' "$input" | jq -r '.model.display_name // .model.id // "Claude"')
size=$(printf '%s' "$input" | jq -r '.context_window.context_window_size // empty')
used=$(printf '%s' "$input" | jq -r '.context_window.total_input_tokens // empty')
pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty')

if [ -n "$size" ] && [ -n "$used" ]; then
  left=$(( size - used ))
  [ "$left" -lt 0 ] && left=0
  printf '%s | Лимит чата: %s / %s токенов (осталось %s)' "$model" "$used" "$size" "$left"
elif [ -n "$pct" ]; then
  printf '%s | Лимит чата: использовано %s%%' "$model" "$pct"
else
  printf '%s | Лимит чата: нет данных' "$model"
fi
