# PawPal+ Care Knowledge Base

Retrieval corpus for the care-suggestion feature. `retrieval.py` parses this
file into `Chunk` objects and selects the few that match a given pet; the
selected text is the *only* care information the model is allowed to draw on.

**This is illustrative course material, not veterinary advice.** Guidance here
is deliberately routine (walk lengths, grooming cadence, feeding rhythm) and
avoids anything diagnostic or dose-related.

## File format

Chunks are separated by a `<!--CHUNK-->` line, which must stand alone on its
own line — that is why this sentence can mention it without becoming a chunk.
An HTML comment is used as the delimiter so the file still renders as ordinary
Markdown while staying trivial to split without a YAML dependency.

Each chunk is a header of `key: value` lines, then a blank line, then the body
text that gets sent to the model. List values are comma-separated.

| Key | Meaning |
| --- | --- |
| `id` | Stable slug. Cited in model output and written to logs — don't renumber. |
| `species` | Which species this applies to. Omit for species-agnostic advice. |
| `breeds` | Only match pets whose breed contains one of these phrases. |
| `conditions` | Only match pets whose `medical_condition` contains one of these. |
| `age_min` / `age_max` | Age band in years, inclusive. Skipped if the pet's age is unknown. |
| `avoid` | Activity keywords this pet should not be scheduled for. Feeds conflict detection. |
| `always` | `yes` marks baseline advice that matches any pet of that species. |

A chunk matches only if **every** constraint it declares is satisfied, so a
chunk with no constraints beyond `species` is general advice.

## Authoring rules

1. **Put concrete numbers in the body.** The model lifts durations and
   frequencies from this text into task fields, so "two 15-minute walks" is
   usable where "regular exercise" is not.
2. **Never tag a condition with a bare shared word.** Tag `hip dysplasia`, not
   `dysplasia` — the latter would also match `elbow dysplasia` and produce care
   tasks for a disease the pet doesn't have. Matching is whole-phrase, so a
   specific tag still matches `mild hip dysplasia`.
3. **Keep bodies short.** Two to four sentences. Several chunks share the
   prompt, and long chunks crowd each other out.

<!--CHUNK-->
id: dog-general-daily-walks
species: dog
always: yes

Most dogs need at least two walks a day, 20 to 30 minutes each, ideally one in
the morning and one in the evening. Consistent walk times help with toilet
routine and settle anxious dogs.

<!--CHUNK-->
id: dog-general-feeding
species: dog
always: yes

Feed adult dogs twice daily at consistent times, roughly 12 hours apart. Each
feeding takes about 10 minutes including fresh water. Measure portions rather
than free-feeding.

<!--CHUNK-->
id: dog-general-dental
species: dog
always: yes

Brush a dog's teeth daily where possible; 5 minutes is enough. Daily is far
more effective than occasional longer sessions, so a short slot every evening
works better than a weekly deep clean.

<!--CHUNK-->
id: dog-general-enrichment
species: dog
always: yes

Set aside 15 minutes of daily training, scent games, or puzzle feeding.
Mental work tires a dog as effectively as physical exercise and reduces
destructive behaviour on days when walks are cut short.

<!--CHUNK-->
id: cat-general-litter
species: cat
always: yes

Scoop litter trays daily — about 5 minutes — and do a full litter change
weekly, which takes around 15 minutes. Cats will avoid a soiled tray, so
daily scooping is the single most important routine task.

<!--CHUNK-->
id: cat-general-feeding
species: cat
always: yes

Feed cats two measured meals a day, about 10 minutes each including fresh
water. Cats drink less than dogs, so wet food and a clean water source placed
away from the food bowl both help.

<!--CHUNK-->
id: cat-general-play
species: cat
always: yes

Give cats two interactive play sessions a day of about 10 minutes each, using
a wand toy or chase toy. Short frequent sessions suit a cat's natural hunting
pattern better than one long session.

<!--CHUNK-->
id: cat-general-dental
species: cat
always: yes

Brush a cat's teeth for about 5 minutes daily if they tolerate it, building up
slowly from touching the muzzle. Dental disease is very common in cats and
routine brushing is the main preventive care an owner can give.

<!--CHUNK-->
id: dog-puppy-routine
species: dog
age_max: 1

Puppies need short, frequent outings rather than long walks: three to four
10-minute sessions a day. Add a 10-minute socialisation or handling session
daily, and expect toilet breaks every couple of hours.

<!--CHUNK-->
id: dog-senior-mobility
species: dog
age_min: 7
avoid: stairs, jumping

Older dogs do better on shorter, more frequent walks — two 15-minute outings
beat one 40-minute walk. Keep routes flat, allow extra warm-up time in cold
weather, and give 5 minutes daily to checking joints and paws.

<!--CHUNK-->
id: cat-kitten-play
species: cat
age_max: 1

Kittens play in short bursts: aim for four or five 5-to-10-minute sessions
spread across the day. Include 10 minutes of daily handling so grooming and
vet visits stay easy later in life.

<!--CHUNK-->
id: cat-senior-monitoring
species: cat
age_min: 10

Senior cats groom themselves less, so add a gentle 10-minute brushing session
daily. Spend 5 minutes a day noting water intake, appetite, and litter tray
use — changes in those three are the earliest signals worth reporting.

<!--CHUNK-->
id: dog-hip-dysplasia
species: dog
conditions: hip dysplasia
avoid: stairs, jumping, running, agility

Swimming is the best exercise for hip dysplasia — 15 to 20 minutes of
low-impact movement without loading the joint. Replace long walks with three
short 10-minute flat walks, and give 10 minutes daily to prescribed joint
supplements and a warm, well-padded bed.

<!--CHUNK-->
id: dog-arthritis
species: dog
conditions: arthritis
avoid: jumping, stairs, running

Keep arthritic dogs moving with gentle, regular exercise: three 10-to-15-minute
walks daily rather than one long one. Add 10 minutes for a warm bedding check
and gentle massage, and keep weight down since every extra kilo loads the
joints.

<!--CHUNK-->
id: dog-diabetes
species: dog
conditions: diabetes

Diabetic dogs need meals and medication on a strict 12-hour schedule — the
timing matters more than the exact hour. Allow 5 minutes twice daily for
medication alongside each meal, and keep exercise consistent day to day rather
than heavy one day and light the next.

<!--CHUNK-->
id: dog-heart-disease
species: dog
conditions: heart disease, heart murmur
avoid: running, agility, strenuous exercise

Dogs with heart conditions should have gentle, short exercise: two 10-minute
flat walks daily, stopped early if they tire. Allow 5 minutes twice daily for
medication and 5 minutes to count resting breathing rate while the dog is
asleep.

<!--CHUNK-->
id: dog-skin-allergies
species: dog
conditions: skin allergies, allergies, atopic dermatitis

Allergy management is mostly routine: a 20-minute medicated bath weekly, and a
5-minute paw and belly wipe-down after every walk during pollen season. Keep a
short daily note of which areas the dog is scratching.

<!--CHUNK-->
id: dog-obesity
species: dog
conditions: obesity, overweight

Build walk length up gradually rather than jumping straight to long outings:
start at two 20-minute walks and extend by 5 minutes a week. Measure every meal
and replace food treats with a 15-minute training or play session.

<!--CHUNK-->
id: dog-dental-disease
species: dog
conditions: dental disease, periodontal disease

Dogs with existing dental disease need daily brushing without exception — 5
minutes each evening with a soft brush. Add 5 minutes to check for a dropped
appetite or reluctance to chew, which usually appears before visible swelling.

<!--CHUNK-->
id: dog-anxiety
species: dog
conditions: anxiety, separation anxiety
avoid: sudden schedule changes

Anxious dogs settle best on a predictable daily rhythm, so keep task times
stable rather than moving them around. Add a 10-minute calm training or
settle-on-mat session daily, and a 10-minute decompression sniff walk on a long
lead.

<!--CHUNK-->
id: cat-kidney-disease
species: cat
conditions: chronic kidney disease, kidney disease, ckd

Water intake is the priority: set out several water stations and refresh them
daily, about 5 minutes. Feed prescribed wet food on a fixed schedule and allow
10 minutes twice daily for feeding plus any medication.

<!--CHUNK-->
id: cat-hyperthyroidism
species: cat
conditions: hyperthyroidism

Medication timing drives everything here — 5 minutes twice daily, 12 hours
apart, given with food to reduce stomach upset. Add a 5-minute weekly weigh-in,
since weight is the clearest signal of whether treatment is holding.

<!--CHUNK-->
id: cat-diabetes
species: cat
conditions: diabetes

Diabetic cats need insulin and meals on a fixed 12-hour cycle; allow 5 minutes
twice daily for each. Keep portions identical day to day and avoid free-feeding,
because inconsistent intake makes the dose unpredictable.

<!--CHUNK-->
id: cat-arthritis
species: cat
conditions: arthritis
avoid: jumping, high perches

Arthritic cats need their environment adapted more than their exercise changed:
add steps to favourite perches and move food, water, and litter to ground
level. Keep play gentle and short — two 10-minute ground-level sessions daily.

<!--CHUNK-->
id: cat-urinary
species: cat
conditions: flutd, urinary tract disease, cystitis

Litter hygiene and water intake are the two levers: scoop twice daily at 5
minutes each and refresh water stations daily. Stress makes urinary flare-ups
worse, so keep feeding and play at consistent times.

<!--CHUNK-->
id: cat-obesity
species: cat
conditions: obesity, overweight

Portion every meal by weight rather than filling the bowl, and split the daily
ration across two or three feeds. Add a third 10-minute play session and move
the food bowl upstairs or away from the cat's resting spot to build in
movement.

<!--CHUNK-->
id: cat-dental-disease
species: cat
conditions: dental disease, periodontal disease

Daily brushing is non-negotiable once dental disease is present — 5 minutes
each day with a finger brush. Spend 5 minutes checking for drooling, pawing at
the mouth, or eating on one side, all of which appear before the cat stops
eating.

<!--CHUNK-->
id: dog-labrador
species: dog
breeds: labrador, labrador retriever, lab retriever

Labradors gain weight easily and are food-motivated, so measure every meal and
keep treats to training portions. They need 45 to 60 minutes of real exercise
daily, ideally including swimming or retrieve work.

<!--CHUNK-->
id: dog-german-shepherd
species: dog
breeds: german shepherd, alsatian
avoid: jumping

German shepherds need 30 to 45 minutes of exercise plus 15 minutes of
structured mental work daily — they deteriorate behaviourally without a job to
do. Watch the hips and elbows, and keep exercise on soft, flat ground while
young.

<!--CHUNK-->
id: dog-brachycephalic
species: dog
breeds: pug, bulldog, french bulldog, boxer, shih tzu
avoid: heat, strenuous exercise, midday walks

Flat-faced breeds overheat quickly, so keep walks to 10 or 15 minutes and
schedule them in the cool early morning and late evening. Add a 5-minute daily
clean of the facial folds, which trap moisture and become sore.

<!--CHUNK-->
id: dog-border-collie
species: dog
breeds: border collie, collie

Border collies need a job: 60 minutes of exercise plus 20 minutes of training
or scent work daily, split across the day. Without the mental half they invent
their own work, usually herding people or chasing shadows.

<!--CHUNK-->
id: dog-dachshund
species: dog
breeds: dachshund, sausage dog
avoid: stairs, jumping, furniture

Dachshunds are prone to spinal injury, so block stairs and furniture jumping
and use a ramp instead. Keep walks flat and moderate — two 20-minute outings
daily — and use a harness rather than a neck collar.

<!--CHUNK-->
id: dog-poodle
species: dog
breeds: poodle, labradoodle, goldendoodle, cockapoo

Curly coats mat rather than shed, so brush for 15 minutes daily right down to
the skin, not just the surface. Book professional grooming every six to eight
weeks and allow 10 minutes weekly for ear checks, since hair grows in the canal.

<!--CHUNK-->
id: cat-persian
species: cat
breeds: persian, himalayan

Persians need 10 minutes of daily brushing to prevent mats, plus a 5-minute
daily eye wipe because the flat face causes constant tear overflow. Skipping
either for a few days creates problems that take weeks to undo.

<!--CHUNK-->
id: cat-maine-coon
species: cat
breeds: maine coon, norwegian forest cat

Long, dense double coats need 10 minutes of daily brushing, with extra
attention behind the ears and along the trousers where mats start. These are
large, active cats — give them 15 minutes of climbing or chase play daily.

<!--CHUNK-->
id: cat-siamese
species: cat
breeds: siamese, oriental shorthair, burmese

Siamese and oriental breeds are highly social and vocalise when under-occupied.
Give them 15 minutes of interactive play twice daily and leave puzzle feeders
out when the house is empty.
