# Trade Buddy

A phone app that tells a kid whether a trade is fair. Point it at your pile of cards or toys, point it at your friend's pile, and it gives back one clear answer a six-year-old can read.

I built it in an evening for my own kid, then reskinned it into something anyone can use.

## The problem, and the version I didn't build

My six-year-old trades cards and toys with his friends. The trades are chaotic, and once in a while a genuinely valuable card (a hand-me-down from an older sibling) gets swapped away for a stack of commons. He wanted a way to check if a trade was "fair."

The obvious build is a scanner plus a price database: identify every card, look up its market value, total each side, compare. That is the wrong product. These cards are creased, off-condition, sometimes fake, and nearly all worth nothing. Precise dollar values would be expensive to compute and useless in practice.

## The reframe

The job isn't valuation. It's two things:

1. A fairness gut-check, in plain kid language.
2. A safety flag for the one item that actually matters, so a real collectible doesn't get traded away by accident.

That reframe is the whole product. It turns a hard, costly problem (accurate pricing) into an easy, cheap one (coarse judgment plus a "show a grown-up" flag), and it is what an actual parent wants.

## How it works

1. The kid lays out each side's stuff on a red tile and a yellow tile, and takes one photo of each.
2. The browser shrinks both images and sends them in a single vision call, with the two piles labeled inline.
3. The model returns structured judgment only: each item with a rough value tier, which side is heavier, whether anything is a real "treasure," and whether something looks fake. It does not write any sentences.
4. The app writes the kid-facing line itself, in code, from that judgment.

The result is one of a few friendly outcomes: fair, a gentle "this looks a little one-sided" nudge, or a "whoa, show a grown-up first" alert when a genuinely valuable item is on the table. One photo per side, one model call per trade, pennies per check.

## Decisions that carried it

This is a small app. The interesting part is the judgment around it.

- **One call, not two.** Both piles go in a single request, so the model judges the trade holistically and the cost stays at one call per check.
- **The model judges; code writes the words.** Letting the model write the kid-facing sentence produced grammar and number-agreement mistakes (it once said "keep some of your cards" when there was a single card). Now the model returns only structured fields and the app assembles the sentence, with correct singular and plural every time. The part LLMs are unreliable at (mechanics) is handled by the part that is perfectly reliable at it (code).
- **Generous by default, strict where it counts.** Junk-for-junk is fair. The app only stops the show for a real rip-off or a real-money item. The goal is to let kids trade freely, with a safety net for the rare case that matters.
- **Honest about bad input.** A photo that isn't cards or toys (I tested it on a pen and a hairbrush) returns "I don't see anything to trade," instead of inventing a verdict.
- **Cost-aware.** Client-side image downscaling keeps token usage down, and a small built-in dashboard tracks estimated spend per model so I can compare a stronger model against a cheaper one.
- **Graceful failure.** Any error degrades to a friendly "try again" screen, and the real reason goes to the logs.
- **Licensing and IP handled on purpose.** The display font is Jost, a free web-hostable geometric sans, rather than Futura, which is paid and cannot be legally bundled. The original card-game-themed build stayed private; this public version is a clean reskin with neutral art so it can actually be shared.

## Does it work

Yes. The original build correctly flagged both a 1999 vintage chase card and a modern secret-rare chase card as treasure, twenty-five years of releases apart, which is the exact safety case it exists for. It catches modern sought-after items, not just old ones, so it is not simply keying on "old equals valuable."

## What it is, and isn't

It is a deliberately small tool: one screen, one model call, one clear answer. It is not a catalog or a pricing engine, by design. The value here is not lines of code. It is choosing the right problem, shipping something a child can actually use, and being disciplined about cost, failure modes, and licensing.

## Stack

Python and FastAPI, a vanilla installable PWA (no front-end framework), Anthropic Claude for vision, deployed as a single service on Railway.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app:app --reload
```

Open http://localhost:8000 and take two photos. Optional environment variables: `MODEL` to switch models, `STATS_KEY` to gate the `/dashboard` cost view, `DATA_DIR` to persist the cost counters across restarts.
