
# Agentic Stock Digest System


## The Product

Every day, you will receive an email about research digest on promising stocks.

In each digest email, it will include the following:
* A summary of trending stocks and their corresponding industry
* Pick the most bullish industry and explain why market is so bullish on it
* Research on the next technological frontier and the upcoming business context of the industry
* Based on the research, recommend top 3 stocks of the industry that will benefit from future developments but not priced in yet. Also estimate when the trend will start to be recognized by market and therefore those stocks' price will pick up, to make it more actionable.


## The System

`send_digest.py` is the main script to generate stock digest by interacting with model APIs, put together an html body based on API responses, and send emails.

`utils` folder has the necessary util functions including html generation and email sending.

Scheduling is implemented through github actions.


## Next Steps

* Allow easy adding more email recipients
* Establish a feedback mechanism by incoporating the thumbs up/down signals into prompt
