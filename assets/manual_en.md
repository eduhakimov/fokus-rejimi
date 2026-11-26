# Focus Mode

## Timer
1. Type what you are working on in **Task** (optional).
2. Press **Start** or click the ring. A focus session lasts 25 minutes.
3. A short break follows each focus session, and a long break follows every 4th one.
4. The left button stops the timer, the right one skips to the next phase.

Lengths and automatic starts are set on the **Settings** page.

## Blocking apps
- On the **Blocking** page, type a process name (for example `steam.exe`) or pick one with **From running...**.
- Choose an action for each app: **Close** or **Minimize**.
- If a listed app starts during focus, a warning appears at the top of the screen. After the delay (10 seconds by default) the app is closed or minimized.
- Only apps on your list that run under your own account are affected. System processes such as explorer.exe or svchost.exe cannot be added.
- Save your work first: unsaved data in a closed app may be lost.

## Blocking websites
- Turn on **Block websites during focus** and add domains.
- This edits the Windows `hosts` file, so the app has to run as administrator. It offers to restart itself.
- The block is active only during focus and is removed on breaks, on stop and on exit. If the app ends unexpectedly, the block is removed the next time it starts.
- Before every change a copy of hosts is saved to `%APPDATA%\BahtiyorSoft\fokus-rejimi\backups`.
- If a browser still opens a blocked site, reload the page or restart the browser.

## Strict mode
During focus, pausing, stopping, skipping and quitting require typing a phrase. You can change the phrase in Settings. While focus runs, block lists and timer settings are locked.

## Statistics
Focus time today, completed pomodoros, day streak and interrupted sessions. The chart shows 7 or 30 days; the dashed line is your daily goal. Sessions shorter than a minute are not recorded.

## Notification area
If you close the window while the timer runs, the app stays in the notification area. Hover the icon to see the remaining time. The right-click menu has the timer controls.

## Break reminder
When a break starts, the screen is dimmed. **Skip break** moves on to the next focus session, **Hide** or Esc only closes the reminder. It can be turned off in Settings.

## Start with Windows
When this option is on, the app starts in the notification area when you sign in to Windows. It is off by default.
