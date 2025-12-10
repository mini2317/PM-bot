#!/bin/bash
echo "🗑️  Removing database files..."

if [ -f pm_bot.db ]; then
    rm pm_bot.db
    echo "✅ pm_bot.db deleted."
else
    echo "ℹ️  pm_bot.db not found."
fi

#if [ -f memory.db ]; then
#    rm memory.db
#    echo "✅ memory.db deleted."
#else
#    echo "ℹ️  memory.db not found."
#fi

echo "✨ Database reset complete. Restart the bot to recreate tables."