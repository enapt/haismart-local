# How the controls behave

Why some controls appear on one unit and not another, what happens when your air conditioner ignores
a setting, and how the energy and polling side works.

- [Your unit describes itself](#your-unit-describes-itself)
- [Settings that only apply in some modes](#settings-that-only-apply-in-some-modes)
- [Presets](#presets)
- [Swinging and pointing](#swinging-and-pointing)
- [Energy monitoring](#energy-monitoring)
- [How often it polls](#how-often-it-polls)
- [Vane readings on units that cannot be asked](#vane-readings-on-units-that-cannot-be-asked)

## Your unit describes itself

The integration reads your unit's own model: the modes and fan speeds it has, the setpoint range it
accepts, the positions its vanes can hold, and the rules saying which settings it ignores in which
state. A heat pump gets Heat and a cooling-only unit does not, with no list to maintain.

A model describes every function its *product line* might have, and marks the ones a given unit
lacks. Those are left out, so you get controls that drive something and readings that mean
something, rather than buttons that do nothing.

Not everything reported becomes an entity. The firmware version is a property of the unit rather
than a reading that changes, so it appears on the device page and in a diagnostics download.

## Settings that only apply in some modes

Air conditioners ignore certain settings in certain states: a unit in fan-only discards the
temperature you set, and most ignore boost while dehumidifying. Your unit's own model says which.

Those controls **stay visible and keep showing their real state**. What changes is that the command
is refused, naming the reason — *"Eco does not accept that setting: not available in fan-only
mode"*. They are not marked unavailable, because a setting your AC ignores in its current mode is
normal operation rather than a fault, and marking it so takes the reading and its history away for
as long as the mode lasts.

The one thing that does disappear is the temperature box on the thermostat card, which is Home
Assistant's own mechanism for exactly this — better than a box that accepts numbers the unit throws
away. A unit reporting a fault refuses its settings the same way. Nothing is restricted while the AC
is switched off, which is when you are most likely to be setting it up.

## Presets

The climate entity carries presets for the three comfort modes — eco, sleep and boost — so they work
from the thermostat card, from a voice assistant and from `climate.set_preset_mode`, not only from
the switches. A preset is exclusive: choosing one clears the others in a single write. The switches
and the Eco select remain for the individual fields and for choosing which eco level you want.

## Swinging and pointing

Swing comes as both controls Home Assistant offers. The four-way one (off / up-down / left-right /
both) moves the two vanes together; alongside it, `climate.set_swing_horizontal_mode` moves the
left-right vane on its own. Units whose left-right position is not confirmed get only the four-way
control.

Swinging and pointing are different things, and a climate entity can only express the first. Where
your unit publishes the stops a vane can hold, a **Left-right vane** or **Up-down vane** select
appears with those positions on it, so you can aim the airflow at one part of the room rather than
sweeping it across the whole. Fixed and Auto are the two states the swing control already covers;
the positions between them are the ones it cannot reach. Positions are numbered as your unit numbers
them — "Position 1" is the first stop it offers. An axis that publishes only fixed and auto gets no
select, since the swing control says everything there is to say about it.

## Energy monitoring

Units that report their power draw get a **Power** sensor in watts. That is a live reading, so it
records into history and long-term statistics on its own — but the Energy dashboard needs a running
total in kWh, which is a different thing.

**Some units keep that total themselves**, and those get an **Energy** sensor you can add straight to
the Energy dashboard under **Settings → Dashboards → Energy → Individual devices**. It is the figure
the air conditioner's own meter keeps, so it survives restarts and outages and does not depend on how
often Home Assistant polls. If your Energy sensor reads *unknown*, your unit is one of the many that
carries the register and never fills it in — read on.

To build a total from the power reading instead, add a Riemann-sum integral helper over it:

1. **Settings → Devices & services → Helpers → Create helper → Integral sensor**
2. Pick your AC's **Power** sensor as the input
3. Metric prefix **k** (kilo), time unit **hours** — that gives you kWh
4. Method: **Trapezoidal**, the sensible default for a value that ramps

Then add the resulting kWh sensor under **Settings → Dashboards → Energy → Individual devices**.

Two things worth knowing before you trust the numbers:

- **Check the helper's state class is `total_increasing`.** If the Energy dashboard will not offer
  your new sensor, this is almost always why — and a helper left on `total` can produce spikes in
  long-term statistics after a restart.
- **It is an estimate, and so is the manufacturer's.** The figure comes from the unit's own current
  measurement, and integrating a value sampled every 30 seconds cannot capture everything in between.
  The vendor app's energy screens are estimates too — by their own wording, "based on the operation
  status data of devices" — and they stop counting while the unit is offline. For billing-grade
  numbers, use a clamp meter or a metering plug.

The integration never invents a kWh total. Where a unit keeps one you get it as counted; where it
does not, the helper above is the honest way to build one.

## How often it polls

The integration polls every **30 seconds** by default (minimum 10), changeable under the
integration's **Configure** menu. One poll fetches everything in a single connection — status, faults
and the power figures — because these units accept only one connection at a time.

For a different rhythm, Home Assistant has a documented way that works for any integration: open the
integration's **⋮ → System options**, turn off *Enable polling for updates*, and drive it from an
automation calling `homeassistant.update_entity` on whatever schedule or trigger you like. Useful if
you only want frequent readings while the AC is running.

Polling faster than 10 seconds is not offered: each cycle is a full connection to the unit, and the
readings do not change fast enough to be worth it.

The **Cloud connection** sensor refreshes on its own slower cadence, about once a minute, inside the
same cycle. It costs one small UDP exchange rather than a connection, and the underlying state moves
on a scale of minutes.

When you change a setting, the air conditioner confirms it on that same connection, so the thermostat
card reflects the change at once instead of waiting for the next poll. The engineering readings —
power, current, frequency, the coil and discharge temperatures, compressor and fan — are not part of
that confirmation, so they keep the values from the most recent poll. They are held for at most two
minutes, and cleared immediately when you switch the unit on or off, because the figures for a
running unit say nothing about one that has just stopped.

The thermostat's own account of what the unit is *doing* — cooling, idle, drying, heating, fan, off
— comes from the compressor flag among those readings, so it follows the same rule: it holds for the
same two minutes, and where the flag is unknown it reads unknown, with no badge on the card, rather
than echoing the mode. Off and fan-only need no telemetry and are always reported.

## Vane readings on units that cannot be asked

A vane is a position, not a switch. The swing control answers one question — is it sweeping — and on
a unit whose vane holds a fixed direction that answer is the same whether the vane is closed or
pointed somewhere deliberate.

Where the unit accepts vane commands, a control lists the stops its own model publishes and the swing
control keeps working alongside it. Where it does not — an axis its family has no confirmed command for, or a family that is
read-only altogether — the appliance still reports both axes in every status message. Those units get a **reading** for each
axis instead, naming the stop the vane is parked at in the same words the control would use. It is
the only account of the vanes such a unit will give.
