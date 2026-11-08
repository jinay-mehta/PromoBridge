# 2-minute walkthrough outline

1. **Problem (15 sec):** A viewer can see a microdrama ad on social media but fail to find the promised show after opening the app. PromoBridge checks the content-to-catalogue handoff before publishing.
2. **Catalogue (20 sec):** Show the demo catalogue: three fictional shows, eleven episodes, timestamps, episode IDs and evidence spans. Explain that the sample is synthetic and real permitted scripts can be uploaded in the Catalogue tab.
3. **Exact match (35 sec):** Enter `Stop the ceremony! This groom is already married.` and title `The Last Promise`. Show the verified result, Episode 1, scene evidence and timestamp. Explain that the transcript is directly supported by source text.
4. **Safe failure (25 sec):** Enter `A spaceship captain discovers a new planet after the engine fails.` Show `NO MATCH`. Then test a generic short line and show `NEEDS REVIEW`.
5. **Human handoff (15 sec):** Approve a mapping and export the manifest. Point out evidence ID and `UNKNOWN` destination when no destination URL is supplied.
6. **Evaluation (10 sec):** Run the 30-case synthetic set. State that exact positives are retrieved well; paraphrases currently rank correctly but abstain, which is a known limitation.

Do not claim synthetic metrics are production accuracy or that the prototype validates a live Kuku deep link.
