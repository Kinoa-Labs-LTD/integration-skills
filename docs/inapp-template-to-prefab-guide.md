# Turning an In-App Template into a Unity Prefab

## What this module does

Point this module at an in-app template on your Kinoa Dashboard and it builds
the client side of that pop-up in your Unity project: a **prefab** laid out like
the design, and a **view script** that fills it from the in-app message the SDK
delivers and routes every button. The run happens inside Claude Code with the
Kinoa plugin installed, against your open Unity Editor.

It is the second half of a pair. The first module,
*Generating In-App Templates from Design Mockups*, turns a designer's mockup
into a template on the Dashboard. This one turns that template into UI your
game can show:

| Step | Module | Produces |
|---|---|---|
| Design → structure | `kinoa-inapp-template-from-image` | The template on the Dashboard, plus `<template_key>.layout.json` (where each element sits on the design) |
| Structure → client UI | `kinoa-inapp-template-to-prefab` | A prefab and a view script in your Unity project |

You integrate a template once. Operators then ship many in-app campaigns on
top of it, and every one of them renders through the same prefab with no
further client work.

## Before you start

- **Unity is open with a Unity MCP bridge running.** The prefab is built by
  the Unity Editor itself, so this is a hard requirement. Three servers are
  supported: CoderGamester `mcp-unity`, CoplayDev `unity-mcp` and IvanMurzak
  `Unity-MCP`. Without a running bridge the module stops and tells you what to
  install; it never hand-writes a prefab file or hands you a stand-in script.
- **The project uses the Kinoa Unity SDK** (`com.kinoa.sdk.core`). The view
  script binds the SDK's in-app message types, so it cannot compile without it.
- **A Kinoa session is set up** with your game id and a Dashboard session
  token. If it isn't, the module sends you to the init step first.
- **Ideally, the template's layout file.** The best input is the
  `<template_key>.layout.json` the mockup module wrote when the template was
  created. It is optional: see step 3.

## How to run it

```
/kinoa-dashboard:kinoa-inapp-template-to-prefab --template-id <template uuid>
/kinoa-dashboard:kinoa-inapp-template-to-prefab --template-id <uuid> --layout-artifact path/to/summer_bundle.layout.json
```

Without `--template-id`, you pick the template from a short list of your
game's templates. What happens next:

**1. Preflight.** The Unity bridge, the Kinoa session and the SDK are checked,
and the template's full structure is fetched from the Dashboard. The module
also looks for the SDK's sample UI facade, `KinoaUiService`, because button
clicks are routed through it when it exists.

**2. Your existing pop-ups set the style.** You name one or two of your game's
pop-up prefabs. Candidates whose names look like popups, dialogs or offers are
suggested. They are read, never changed, to copy your conventions: legacy
`Text` or TextMeshPro, the font, the panel size, the close-button sprite, and
the canvas settings when the pop-up carries its own canvas.
If they share a base popup class, it is reported to you rather than inherited.
The generated view stays a plain component that your popup manager can wrap.
If your game has no pop-ups yet, you answer one question instead: legacy Text
or TextMeshPro.

**3. The layout is chosen.** Every slot is placed where the design had it. The
sources, in order of preference:

| Source | When to use it |
|---|---|
| **The template's `layout.json`** | You created the template with the mockup module and kept the file. This is the recommended path. |
| **Derived from the template's tip image** | The template exists on the Dashboard but nobody kept its layout. The mockup module analyses the tip image, whether it was attached as a link or uploaded as a file. After you confirm the image, it checks that the image matches the template. You confirm the boxes on its review page, and the layout file is written. |
| **A kept confirmation file, or the raw build result** | You have files from an earlier mockup run but no layout file. The raw build result works, but its boxes were never confirmed by a person. |
| **No layout** | Nothing else is available. Every element is still built, stacked in a clearly marked holding area for you to arrange. |

A tip image that does not match the template, such as an older design or an
unrelated picture, produces no layout at all. Positions are never invented
from it. Note that the check is structural: a *different* design with the
same set of elements passes it, which is why you confirm the boxes on the
review page.

**4. The plan is made and shown to you.** Before any file is written you see
what will be built, including anything that needed a decision. That covers
elements the layout did not place, positions that were estimated, and
anything moved to keep texts and buttons apart (see *Layout and overlaps*).

**5. Your game's own methods are wired in.** The view needs three things the
SDK does not provide: loading a remote image, looking up a store price, and
finding a resource's icon. For each, the module searches your code for an
existing method and asks which one to use. When nothing fits, it leaves a
clearly marked `TODO(kinoa-prefab)` and a runtime warning. It never writes a
downloader or a price lookup of its own; those belong to your game, with its
own caching, threading and store integration.

**6. Code is generated and the prefab is built.** Unity recompiles, the build
runs through the menu item **Tools → Kinoa → In-Apps → Build Prefabs From
Plans**, and the module reads the build report back. A compile error or a
missing field is reported as such. Nothing is claimed as built without the
report.

**7. You get a hand-off.** It lists the prefab, the view class, every
`TODO(kinoa-prefab)` with its file and line, and every warning. It also says
plainly what was verified in Unity and what was not.

## What you get

| File | Owner | What it is |
|---|---|---|
| `Assets/Kinoa/InApps/<Name>/KinoaInApp_<Name>.prefab` | Generated | The pop-up, laid out like the design |
| `Assets/Kinoa/InApps/<Name>/KinoaInApp<Name>View.cs` | Generated | Fills the prefab from an in-app message and routes its buttons |
| `Assets/Kinoa/InApps/<Name>/<key>.inapp-plan.json` | Generated | The plan the prefab is built from |
| `Assets/Kinoa/InApps/Editor/KinoaInAppPrefabBuilder.cs` | Tool-owned | Builds any plan into a prefab; refreshed on every run |
| `Assets/Kinoa/InApps/Shared/KinoaInAppHooks.cs` | **Yours** | Where you assign your image loader, price lookup and icon lookup |
| `Assets/Kinoa/InApps/Shared/KinoaInAppItemView.cs` | **Yours** | The row used for reward items (the resource area and the rewards on a mission card) |
| `Assets/Kinoa/InApps/Shared/KinoaInAppFeatureHooks.cs` | **Yours** | Where you assign the method that runs a milestone (or mission-bar) button's purchase, ad or link action |
| `Assets/Kinoa/InApps/Shared/KinoaInAppMilestoneStepView.cs` | **Yours** | One step of a milestone ladder (a milestone template's, or a mission template's progress bar): score, reward, progress, locked and collected marks, claim button |
| `Assets/Kinoa/InApps/Shared/KinoaInAppMissionRowView.cs` | **Yours** | One mission card: placement, text, status, progress, rewards, action and dismiss buttons |
| `Assets/Kinoa/InApps/Shared/KinoaInAppTabView.cs` | **Yours** | One mission-set tab |
| `.kinoa-inapp-prefab/<key>/` | Working files | Inputs and intermediate files of the run. Keep them out of git. |

The six **yours** files are written once and never overwritten afterwards, so
your edits to them are safe across runs. If you ran an earlier release of this
module, a new run only adds the new files; your existing hooks and
item view are left exactly as they are. Another folder than
`Assets/Kinoa/InApps` can be requested.

## What the generated code does

**Filling the pop-up.** Texts take the operator's copy (`<br>` becomes a line
break) and its text colour. Images load by their content type: a local
resource directly, a remote URL through your image hook. An addressable image
is left as a marked to-do for your own Addressables wrapper. Buttons show
their label, or the store price when they sell something. A slot the operator
left empty is hidden when the template allows hiding it, and an operator's
on/off switch for a slot can only hide it, never re-show something empty.

**Buttons.** Every tap sends the in-app click event. A `close` action closes
the pop-up. Every other action, such as purchase, ad, collect, deep link or
custom CTA, is handed to the SDK sample's `KinoaUiService` when your project
has it. Without it, the view raises a `ButtonClicked` event and leaves a
routing to-do. The impression event is sent once when the pop-up is shown,
and the close event when it closes.

**Client-rendered zones.** The timer, the struck-through price before a sale,
the reward items area and the milestone grand prize are drawn by the client,
not configured as template slots. The prefab includes a hidden area for each
zone the template can use, and the view shows and fills it from the message.
The timer counts down and shows days when more than one remains.

**Milestones.** For a milestone template the view builds a horizontal scroll
with one card per step (score, reward, progress, a locked or collected mark).
The list opens on the first step the player can claim, else the first locked
step, else the last one. Steps the player can claim get an active button that
calls the SDK's collect method. While a request is running, the milestone
buttons ignore taps, so a double tap never claims or buys twice.
Granting the rewards to the player's economy is a marked to-do, placed exactly
where the server has confirmed the claim.

Milestone designs differ in where the claim button sits, and the module
supports both:

- **A button on every step.** Each card has its own claim button.
- **One button under the ladder.** The cards have no button; the single
  button takes over the claim of the step that is ready.

The module picks one from the template's buttons and tells you which it
chose. If the design shows the other one, say so and run it again with that
choice. A button named like "Collect all" or "Claim all" claims ready steps
at once. If that button is itself a plain claim, it claims only the ready
steps that are a plain claim too: a step that must be bought, watched or opened
keeps waiting for its own button. If the button is itself a purchase, an ad or
a link, its action runs first and then it claims every ready step. It is only
active while it has a step to claim. The same rule applies to the main button
under a ladder whose cards have their own buttons. Info or rules buttons never
count as the claim button.

A step button that needs more than a plain claim, such as a purchase, an ad
or a link, is handed to your own game code: you assign the method in
`KinoaInAppFeatureHooks.RunButtonAction`. The step is claimed only after that
method reports success. Your method must always finish, returning `false` when
the player cancels or the action fails: the milestone buttons ignore taps until
it does. Until you assign it, those buttons claim nothing. The module never
writes a purchase handler for you.

**Missions.** A mission template gets a tab per mission set (the previous set
first, labelled `Set 1 (prev)`, then `Set 2`), a vertically scrolling list of
mission cards and, when the template shows a progress bar, that bar as a
milestone ladder: the same horizontal scroll of step cards a milestone template
gets, one per bar step. Cards are ordered Reached, Active, Collected, then by
placement. Each card shows its placement (`P1`), text, status, progress and
rewards, plus an action and a dismiss **×**:

- **Collect** appears on a completed mission that carries a completion CTA
  and claims it through the SDK.
- **Go** appears on a mission in progress that carries a progression
  CTA and raises a `MissionCtaClicked` event (with the mission's set number) for your game to route, because per-mission CTAs are not template buttons. The to-do in the view says how: a deep link or web link goes to your game's router; a *show ad* CTA reports the mission as reached through `Kinoa.Messaging.ReachMissionsProgress` once the ad has finished, then refreshes the view with the returned message; a *close* CTA closes the pop-up.
- **×** appears on completed and collected missions and deletes that mission's
  progress on the server, then hides the card.

A bar step the player can claim has its own claim button, which works exactly
like a milestone step's: a plain claim claims it; a purchase, an ad or a link
runs your `KinoaInAppFeatureHooks.RunButtonAction` first and claims the step
only when it reports success — never for free.

*Reach all*, *Collect all* and *Collect all milestones* buttons exist only when
the template declares a button whose key or name says so; the view then shows
each one only while there is something to act on. These buttons bypass the SDK
sample's `KinoaUiService`: a tap sends the click event and runs the mission
call directly. *Collect all milestones* claims the ready bar steps by the same
rule as a milestone "Collect all" button. That includes the case where its own
action is an ad or a link rather than a purchase: that action also gates steps
that must be bought, and your `RunButtonAction` decides whether they are
claimed — the same as on a milestone template. Every request disables the tabs
and buttons until it returns.

The look comes from the design: the mockup module records the geometry and
colours of the tabs, the cards and the progress bar in the layout file, and the
prefab is built from them (the bar's box places the step ladder, so it should
cover the bar with its markers and rewards). Any part the layout has no box for
gets a neutral default, listed in the plan report. Granting rewards for a
collected mission or bar step, and routing a **Go** tap, are marked to-dos.
Grant a mission's rewards only when the SDK's response shows it as no longer
completed-and-unclaimed (collected or removed), as the SDK sample does — not
for every mission you asked to collect.

## Layout and overlaps

The design's positions are kept, with three guarantees:

- **Nothing outside the art gets squeezed.** On most designs the CTA, timer or
  fine print sit below the background art. The pop-up's area spans every
  element, so these keep their real position and size.
- **Texts, buttons and zones are kept apart where that is safe.** Elements
  placed at a default position move to free space. Two boxes that only graze
  each other are trimmed to meet halfway.
- **Intended overlays are left alone.** A price drawn on the CTA, a badge on
  the art or the reward area on a task list are designed to overlap and are
  kept as drawn. A larger accidental overlap is also left as drawn, with a
  warning, so you can fix the box rather than have it guessed.

Every move and trim is listed in the plan report with its before and after
position. A trim or an overlap warning usually means a box on the review page
was drawn too large. Art is always drawn behind buttons and text and never
takes taps meant for them.

## Your to-dos after a run

1. **Assign the hooks** in your game's startup code: the image loader, the
   store price lookup and the resource icon lookup in `KinoaInAppHooks.cs`.
   Until then, the affected images and prices stay empty and a warning is
   logged.
2. **Check the canvas.** The prefab root comes with a `Canvas`, a
   `CanvasScaler` and a `GraphicRaycaster`. Their settings are copied from
   your reference pop-up when it has its own canvas. Otherwise they are
   pop-up defaults: an overlay canvas at sorting order 100, scaling with the
   screen at the design's size. Render mode, sorting order, reference
   resolution and scale mode depend on your game's UI setup, so align them.
   If you show the pop-up under an existing pop-up canvas instead, remove
   them or keep them as a nested canvas, whose scaler is then ignored. A
   Screen Space Camera canvas needs its camera assigned at runtime.
3. **Register the template key**, if your project uses the SDK sample facade.
   The module offers two one-line edits, a key constant and one switch arm,
   and asks before applying them. Until both are in place, the sample facade
   ignores every tap on this pop-up.
4. **Show the pop-up.** Instantiating the prefab when an in-app arrives belongs
   to your messaging integration, which the SDK's own `/kinoa` messaging setup
   covers. The hand-off includes a code snippet for it.
5. **Fill the marked to-dos** in the view, such as reward granting, routing
   when there is no facade, and addressable images. Every one carries
   `TODO(kinoa-prefab)`. For a milestone template with purchase, ad or link
   buttons, also assign `KinoaInAppFeatureHooks.RunButtonAction` to a method of
   yours that runs the button's action and returns whether it succeeded.
6. **Activate the template** on the Dashboard when the operator configures the
   first in-app on it.

## Deliberate boundaries

- **Rebuilding overwrites the prefab.** The prefab is rebuilt from its plan,
  so changes made by hand inside it are lost on the next build. Adjust the
  layout or the plan and rebuild, or keep your own additions in a separate
  prefab that wraps this one.
- **No network code is generated.** The view never calls the Dashboard,
  never carries an admin token and never downloads anything itself. Any
  generated file containing such code is refused before it is written.
- **The template is only read.** Nothing on the Dashboard is created, changed
  or deleted by this module.

## FAQ and troubleshooting

**The CTA, timer and fine print all ended up in one place at the bottom.**
That was a bug in early builds of this module, fixed since. If you still see
it, your installed plugin copy predates the fix. A plan file whose report has
no `panel_bbox` comes from the old planner. Reinstall the plugin, re-run the
module for the template and rebuild the prefab.

**Generation stopped with `milestone_plan_outdated`.** A milestone template's plan file
was written before the milestone scroll ladder existed. Run the module again for that
template so it plans afresh; nothing was written by the refused run.

**The module stopped right away saying there is no Unity MCP.** Install one
of the three supported servers, open the project in Unity and start its
bridge (for `mcp-unity`: *Tools → MCP Unity → Server Window → Start Server*),
then run the module again. If you only want the plan file without a prefab,
ask for that explicitly.

**Taps on the pop-up do nothing.** Check three things in this order. Is the
prefab's `GraphicRaycaster` still there and enabled, or is there one on the
canvas above it if you removed it? Are the template-key constant and switch
arm applied in your sample facade? Is the action's handling filled in your
facade?

**An image never appears.** Remote images load through your image hook. If
the hook is not assigned, a warning in the Unity console says so.

**The text looks wrong: the wrong font, or TextMeshPro expected.** The text
system and font come from the pop-ups you named in step 2. Name a pop-up that
uses the look you want, or answer the TextMeshPro question accordingly, and
re-run.

**The build failed with a compile error.** The hand-off shows the error. The
generated files are regenerated, not patched by hand. A wrong facade
namespace or a missing TextMeshPro package is fixed at the input and the run
repeated. If the error is in one of your own shared files, the module asks
before rewriting it.

**Unity asks to save the scene after the build.** The builder works through
the open scene, so the scene may be left marked as changed. Nothing in it was
meant to be kept; you can discard the change.

**The `Editor` folder breaks our player build.** If the output folder sits
under one of your assembly definitions, give its `Editor/` subfolder its own
Editor-only assembly definition.

**A milestone step's button does nothing.** If its action is a purchase, an
ad or a link, it needs `KinoaInAppFeatureHooks.RunButtonAction` assigned; the
Unity console shows a warning until it is. A plain claim works without it. The
same holds for a step of a mission template's progress bar.

**The milestone design has one button, but every card got its own.** The
module chooses from the template's buttons. Run it again and ask for a single
button under the ladder (the other way round works the same).

**Collect all / Reach all / Collect all milestones are missing.** The module
only builds them when the template has a button whose key or name says so (for
example `collect_all` or `reach_all`). Add such a button to the template and run
the module again. `Collect all milestones` also needs the template's progress
bar to be shown.

**The mission cards look generic.** The layout file has no missions geometry,
so tabs, cards and bar use neutral defaults. Re-derive the layout from the
template's tip image (the mockup module's path for templates that already exist
on the Dashboard) and run this module again.

**The mission progress bar's steps are squeezed.** The layout's box for the bar
covered only the bar line. The plan report warns about it; re-derive the layout
so the bar's box includes its markers and rewards, or resize `MissionBarScroll`
in the built prefab.

**A mission row shows `[]` in its text.** Mission text can carry a
placeholder that your game substitutes, such as the goal score. The view
shows the Dashboard text as-is.

**A Dashboard call failed with `401`.** Your session token expired. It lasts
about 24 hours. Fetch a new one from Dashboard → **Integration**, re-run the
init step, then run the module again.
