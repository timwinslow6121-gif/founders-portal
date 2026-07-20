\- Is there an easy way to incorporate Gemini to the founders Portal?  
\- need to make BOB importer  
\- how to test calendly/quo/healthsherpa integrations?  
\- sales pipeline  
\- campaigns via SMS/email/phone based on plan, t65, etc  
\- customer timeline inside customer profile (any and all updates/interactions/communications)  
\- add filtering to all tables  
\- anytime a customers name appears (Bob import/upload, commission, to-dos/tasks, etc) hyperlink back to their entry/profile   
\- need to be able to edit customers information, currently can't do that.  
\- need primary/secondary owners/AOR  
\- easy way to run reports/filter customers based on any data point (i.e. carrier/plan/Medicaid level/c-snp or d-dsnp, county, zip code, pharmacy, email, cell/mobile/home)   
\- interesting thought: if I only want one entry in the Founders Insurance Agency database per customer, which means 1 entry per MBI. What would happen when an agent (say Brian) tries to create a profile for a customer that is already active with a different agent (say Tim)? Tim has Sarah Jones as a customer, and then Brian tries to create a a new entry for Sarah Jones. Obviously, he adds the date of birth and MBI, and since I don't allow a duplicate MBI to be created, I don't allow Brian (or whoever is the non-AOR) to view that client. I guess I need to change that to where, if an agent that's not the agent of record tries to create a profile, it blocks the creation of the profile. But It still allows the non-agent of record to view that customer's profile, but it does not show who the current agent of record is.

Maybe we just allow every agent search-only access to the entire customer database. That way, if someone calls in through the Founders main line, then any agent can look up who that customer is and who the current agent of record is. Don't allow the running of reports or the ability to see other agents' books of business, just allow the searching of customers for AOR only but allow Brian or other agents secondary access to a customer profile so they can be added to that agents Bob? See, this got me thinking. There's going to be at least a week, up to the three-month overlap during the OEP, where the current agent of record is one agent. If that customer is serviced by a different poachers, then a different agent will be the agent of record for a future start date. That agent of record for the future start date will still need to see that in a sales pipeline and in their book of business for a future active date. The agent that is currently the active agent of record will still need to see that customer in their book of business until they are no longer the agent of record. 

\-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_-\_

Dashboard page fixes:   
There are two bars at the top of the dashboard page. Pending terminations and upcoming terminations are listed in both bars, and active policies and active rob across six carriers are on both bars as well. Unified timeline is great\! However, for upcoming terminations or outstanding tasks, I need to be able to click on that task and have it take me to the person or the customer's profile. 

In the bottom right corner, we have the NC Enrollment Windows. We can probably just get rid of that completely. No need to do that\! Instead of NC Enrollment Windows, maybe we have important information like current SEPs or 5 star sep plans available. 

Customers page:  
In the customers page, we need to be able to sort by:  
\- name  
\- stage  
\- pharmacy

We need to be able to adjust the column width for:  
\- name  
\- MBI  
\- phone

We also need to be able to pick and choose what information we display underneath the customers. As well as being able to audit our book of business to make sure we don't have more customers in there more than once. For example, if we have a customer that has two or three policies with us, we just need one line in the customers. When we click on that customer's name, we're able to see all of their policies with us, but it's only one row in our customer database. 

We need a way to import customers from a CSV or Excel. Since most of us already have all of our customers in a CSV or Excel format, being able to import and upload the current information we have for them into the Founders Portal would be invaluable versus having to restart that process. 

Upcoming terminations:  
I don't know if upcoming terminations need its own page or not. Maybe, but when it comes to Medicare, 30-60 days and 60-90 days are not really options for upcoming terminations. It's always going to be within the next 30 days. It'll be the first of the upcoming month. It'll never be more than 30 days out unless we're in AEP, in which case we would have a separate AEP dedicated page. 

New pages to add:  
We need a new page and database for carriers and plans. We need a database of:  
\- All Unite Healthcare plans  
\- All Aetna plans  
\- All HealthSpring plans  
\- All Blue Cross Blue Shield plans  
\- All devoted plans  
\- All Wellaby plans  
\- GTL plans

That information needs to be integrated with our customer database as well, so that when we click on a customer's profile, we can see what plan they're on. We can click on that plan. It'll take us to that plan, and it'll provide us with some overview information of that particular plan, like the year, the carrier, and some basic information on that plan. It'll also show all of our other customers that are currently on that plan as well. 

Design/UI:  
I need to change the theme to be light mode. Currently it's only a dark mode theme, and it makes it hard to see, especially with the colors that we have gone with. Let's make a light mode theme. Let's add some more padding, rounded corners, and make everything a little bit more visually easy to navigate. 

Add founders logo, update UI to be more modern and simple. Add agents headshots to their profile

Consolidate the side bar, make it minimizable, add more icons with words for sections/modules 

Add tooltips

Add a user guide 

Review dribbble, figma, etc for CRM and sales pipeline UI/UX inspo

\- What if I had some type of AI voice memo thing that allows agents to record a voice note regarding their appointments for the day:  
\- who they talked to  
\- what was done  
\- what they accomplished

Sometimes it's hard to keep track of who we talked to and when and what we just discussed, because a lot of times there's impromptu stuff that pops up. Someone just walks in and we don't have a record of what we discussed. Two, three, four, five days later we forget what we discussed and with whom and what we said we were going to do and all that stuff.

Some type of ability to record, write down what was talked about with whom, and tie that in with their profile or create a task with it, and then create some type of end-of-day recap in the evening (say 6:00 or 7:00 p.m.), whatever time the agent wants to do it. In the morning we have some type of daily update or daily briefing that basically tells us:  
\- Hey, you talked to this person yesterday.  
\- You're supposed to do this on this upcoming day.  
\- Don't forget to do that.  
\- You've got a couple of birthdays coming up at the end of the month. Make sure you remember to do that.

Blah, blah, blah, blah.

Basically, since we're Google Workspace integrated, we have Gemini, and I know Gemini sends me a daily briefing. It takes into consideration emails, texts, phone calls, and calendar stuff. Is there any way to integrate that without being cost-prohibitive? 