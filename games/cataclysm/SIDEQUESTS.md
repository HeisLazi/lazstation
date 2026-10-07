# Haven Story - side quests

## Design rules for every side arc

1. **30+ minutes, wild ride, distinct flavor.** No two arcs share a shape.
   If Act 1's main chain is fetch -> fight -> fix, sides must be other
   verbs: raid, con, escort, investigate, survive.
2. **Dialogue does the work.** Nobody replays a fetch. People replay Kess.
   Every arc has at least one scene written to be quoted back at us.
3. **Loot is the reward.** Completion payouts stay small (a blade, meds, a
   patch). The real pay is what you pry out of the clinic, the lab, the
   toll booth while you're in there. Missions never gatekeep loot.
4. **Fail forward, pick one.** Where an arc branches, both finales stay
   completable and the mission text says *pick one* - the other goes stale
   in-universe. No dead ends, no missable main-chain items.
5. **Sandbox-safe.** Any survivor can offer any side (`ORIGIN_ANY_NPC`).
   Named characters (Morrow, Kess) are roles the dialogue casts onto
   whoever hires you - same convention as Tom/Micah/Lena.

---

## Arc A - THE CURE THAT BITES (implemented, v1.1)

Flavor: heist-horror with a joke that stops being funny.
Time: 30-45 min. Chain: VEX1 -> VEX2 -> choice of VEX3A / VEX3B.

**Cast.** Dr. Morrow - cheerful, well-fed, smells of bleach; the only man
at the crossroads still wearing a clean coat. Kess - Ash Jackals
lieutenant, dry as dust, counts bullets like other people count breaths.
The Ash Jackals - a gang you met yesterday, currently deciding whether
you're prey.

**Beats.**
1. The Jackals clock you and decide you're useful. Kess does the talking.
2. Morrow's pitch: a cure, built from clinic research, needs hands.
3. Supply run (VEX1): one bottle of disinfectant. Easy. Too easy.
4. The Jenner Clinic job (VEX2): clear the dead out of a picked-clean
   clinic so Morrow's folder can come home. Eight of them. The folder is
   heavier than paper should be.
5. The notes (discovery, VEX2 success text): Specimen 12 ate Specimen 11
   and Morrow wrote *promising* in the margin. He isn't making a cure.
   He's making stronger zombies and calling the failures data.
6. The choice - mission text says it straight: *pick one.*
   - VEX3A, alone: walk into Morrow's lab and kill Specimen 12 yourself.
     Near-suicide. A brute in a small room. Nobody sane does this, which
     is why the crossroads will talk about it forever.
   - VEX3B, with the Jackals: bring fire, they bring bodies. Fifteen dead
     between you and Morrow's bench. Kess calls it "pest control with
     witnesses."
7. Aftermath: Morrow's fate differs (see dialogue), the Jackals remember
   you, and Morrow's last letter points at Glass City - Act 3's hospital.

**Money lines (also in the JSON, in full).**

Morrow's pitch (VEX1 offer):
> "People hear 'stronger zombies' and they panic. I hear it and I take
> notes! The pathogen is iterating, friend - every generation fitter than
> the last. So why shouldn't WE iterate faster? Bring me one bottle of
> disinfectant, just to sterilize the bench, and I'll show you the future
> of medicine. It sparkles. It really does."

Kess, on hiring you (VEX1 advice):
> "Doc pays in antibiotics and promises. Promises don't stop bleeding,
> so you take the antibiotics first and believe him later. That's gang
> policy. That's also just policy."

The discovery (VEX2 success):
> "You skim the folder on the walk back. Page nine: 'SPECIMEN 12 ATE
> SPECIMEN 11. Promising.' Page ten is a shopping list. Human growth
> hormone is ON it, underlined twice. Your hands do the shaking for you.
> Morrow isn't making a cure. He's making CUSTOMERS."

Kess rallying the gang (VEX3B accepted):
> "Listen up! The bleach man built a better zombie and kept the receipts!
> We go tonight, we bring fire, and the new kid brings the grudge. Anyone
> who dies gets named after a cocktail. MOVE."

Morrow, cornered, solo ending (VEX3A success):
> "Wait - WAIT. Do you know what you've DONE? Twelve was WEEKS from
> docile! Weeks! ...Fine. Note this down. 'Final observation: the
> specimen was me.'"

**Loot, not rewards.** The clinic holds pharma-room leftovers, the lab
holds Morrow's stash (including the panacea he swore didn't exist).
Completion payouts: antibiotics, a panacea, a molotov, the Jackal patch.
Small. The shelves are the salary.

---

## Arc B - THE TOLL AT MILE 12 (planned, next update)

Flavor: talky heist-comedy. Four solutions, one booth.
Time: 30-40 min.

The Turnpike Saints - four deserters with a barrier, a bell, and absolute
confidence - toll the only good road east. The crossroads is paying. You
can: **pay** the toll (rich route, costs trade goods, Saints love you);
**race** it (vehicle + driving check, nighttime, hilarious); **con** it
(speech: sell them "toll insurance" until their own ledger confuses them);
or **fight** it (hard, four armed humans - the game's first human fight,
framed as tragedy, not triumph).

Tentpole - the Saints' sergeant, Heller, explaining the toll (offer):
> "Two cans per axle, one per soul, half a soul per dog - dogs count
> double, it's the barking. This is all written down. There is a LEDGER.
> You want anarchy? The ledger says you don't."

Con-route beat - selling Heller his own toll (advice):
> "Repeat after me: for a small monthly fee, the Saints never pay tolls
> anywhere, including here, including to themselves. Yes, it's circular.
> Money is circular, son. That's why coins are round."

Loot: the booth's strongbox and the Saints' armory (fight/race), or the
Saints as permanent road friends with a discount (pay/con). Links: the
Saints' map of patrols becomes Act 2's route planner.

---

## Arc C - THE SILO THAT HUMS (planned, next update)

Flavor: quiet horror. The only arc with no jokes until the end, when you
need one.
Time: 30-45 min.

A grain silo two miles off-route hums at night on exactly 91.1. Inside:
no zombies, no people, warm air, and wheat growing UP out of the bins
toward a light that isn't there. Investigation in four visits (each dusk
changes something), piecing together that the silo is *receiving* Haven's
broadcast the way a bowl receives rain - and something else is listening
on the same frequency. Ends with a choice: burn it (crossroads sleeps
better, Act 4 gets harder to explain) or tune it (keep a once-per-story
emergency signal, but mark yourself for whatever listens).

Tentpole - the farmer who won't go back (offer):
> "Third night I heard my wife calling from the top of the silo. She died
> in the first week, in our kitchen, and I buried her myself. So I did the
> arithmetic, same as you would. Four rungs up I stopped climbing, because
> whatever knew her voice didn't know she always called me 'you stubborn
> mule.' It just said my name. Like reading it off a list."

Loot: pre-fall emergency stores in the silo office, untouched because
nobody stayed long enough to pry them open. Links: direct prequel to
Act 4 (Static) - the hum is the same phenomenon.
