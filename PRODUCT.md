# ReTryp: product context

> Draft assembled from SPEC.md, README.md and AGENTS.md. Review and edit before
> running `/impeccable init`. The "Design intent" section is an interpretation,
> not something your docs state. Change it if it is wrong.

## Users

Travellers whose journey has just broken, or is about to. They are often on a
phone, in an airport, a station or a taxi, short on time and under stress, and
sometimes working in a second language in an unfamiliar country. The questions
in their head, in order: *What is affected? What are my options? What happens if
I pick one? Is it actually done?*

A second group plans multi-leg trips ahead of time (flights, rail, buses,
transfers, hotels, several destinations) and wants them held in one place. They
are calmer, usually on a laptop, and judge the product on whether it feels
trustworthy enough to rely on when things go wrong.

Corridors in scope today: India and Europe (Indian rail and bus services,
DGCA and EU261 passenger-rights rules, INR and EUR display currencies).

## Product Purpose

ReTryp holds a traveller's whole journey. When a leg breaks it works out the
effect on every later leg, hotel and transfer, builds several complete recovery
plans, compares them, applies the one the traveller approves, and keeps
monitoring. Success means a traveller understands their situation within
seconds, can approve a plan with confidence, and is never misled about what is
real data, what is simulated, and what has actually been changed.

## Platform

web (responsive). Phone-first for anything used during a disruption: Active
Journey, Recovery Center, Plan detail, Notifications. Desktop-first is
acceptable for planning: Journey Builder, Bookings, History, Settings.

## Design intent

The calm competence of a first-class lounge at the moment everything goes
wrong. Premium travel-brand polish (confident, editorial, spacious, image-led
where the moment allows) combined with the precision of airport signage.
Reassuring under pressure, never playful during a disruption. The product
should feel expensive because it is exact, not because it is decorated.

Suggested surface modes (a page's brief records the final call):

- Persuade: sign-in, sign-up, and any signed-out landing section.
- Operate: Dashboard, Recovery Center, Plan detail, Journey Builder, Bookings,
  Notifications, History, Profile, Settings.
- Experience: Active Journey timeline and Map, where the route itself is the
  content.

## Principles

1. **Truth over spectacle.** Every outward-facing data point carries
   provenance: LIVE, CACHED (with fetched-at time), REFERENCE, SIMULATED or
   UNAVAILABLE. Show it. Never present a cached, reference or modelled value as
   live. A source that cannot answer says so; it is not filled in.
2. **The engine is invisible.** No "AI" or "AI-powered" labels, no sparkle or
   brain icons, no agent names, no chat-style main screens, no confidence
   percentages. The brand is just ReTryp.
3. **Honest execution.** Never imply a real ticket was rebooked. The only
   execution states are: Change requested, Pending provider confirmation,
   Confirmed (demo).
4. **Status is never colour alone.** Colour plus icon plus text label, always.
5. **Time is local and explicit.** Stored in UTC, shown in the local time of the
   airport, station or hotel with the zone visible. Tabular numerals for times,
   durations and money.
6. **One decision at a time during a disruption.** The recommended plan is
   always Plan A and always first. Comparison exists to confirm a choice, not
   to invite browsing.
7. **Beauty serves orientation.** Imagery and motion belong where the
   traveller is exploring or arriving. Where they are deciding, restraint wins.

## Brand commitments (do not break)

- No glassmorphism, neon, glow or hologram effects.
- No invented testimonials, customer or partner logos, or statistics. Any
  illustrative figure is labelled as illustrative.
- No emoji used as icons. Icons come from the existing Lucide registry.
- The product works with zero API keys and says in the UI which data mode it is
  in.
- Spelling is British (traveller, colour, organisation).

## Terminology

Journey (the whole trip), Leg or Segment (one flight, train, bus, transfer or
hotel stay), Disruption, Recovery plan (lettered A, B, C, D; the recommended
plan is A), Recovery Center, Scenario Simulator, Active Journey, Provenance.

## Accessibility & Inclusion

- WCAG 2.2 AA contrast as a floor; keyboard operable with visible focus.
- Respect reduced-motion on every non-essential animation.
- Touch targets of at least 44px on mobile.
- Legible outdoors in bright light and on low-end phones over slow airport
  networks; keep images and scripts light.
- Plain language, short sentences and no jargon in disruption and execution
  states. Readers may be stressed and may not be native English speakers.
- Theme: light only today. Whether to add dark mode is open for the design to
  propose.
