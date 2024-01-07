import discord
import requests
import random
import boto3
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize a DynamoDB resource
session = boto3.Session(
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('REGION_NAME')
)
dynamodb = session.resource('dynamodb')
DiscordID_table = dynamodb.Table('DiscordUsers') 
solved_problems_table = dynamodb.Table('SolvedProblems') 
# Define the intents
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

# This dictionary will map Discord user IDs to Codeforces usernames
user_cf_handles = {}

def get_random_problem(min_difficulty, max_difficulty, solved_problems):
    # URL for the Codeforces API endpoint to fetch problemset
    url = 'https://codeforces.com/api/problemset.problems'

    # Make a request to the API to get the problemset
    response = requests.get(url)
    if response.status_code != 200:
        return "Failed to retrieve problems from Codeforces."

    data = response.json()
    if data['status'] != 'OK':
        return "Error retrieving problems from Codeforces."

    problems = data['result']['problems']

    # Filter problems based on difficulty and whether they have been solved
    filtered_problems = [
        problem for problem in problems
        if 'rating' in problem
        and min_difficulty <= problem['rating'] <= max_difficulty
        and f"{problem['contestId']}{problem['index']}" not in solved_problems
    ]

    if not filtered_problems:
        return "No unsolved problems found in the specified difficulty range."

    # Select a random problem from unsolved problems
    random_problem = random.choice(filtered_problems)

    # Construct the URL for the problem
    problem_url = f"https://codeforces.com/problemset/problem/{random_problem['contestId']}/{random_problem['index']}"

    # Format the selected problem details
    problem_details = {
        'name': random_problem['name'],
        'rating': random_problem['rating'],
        'url': problem_url
    }
    return problem_details

def get_stored_solved_problems(discord_id):
    try:
        response = solved_problems_table.get_item(
            Key={
                'discordID': str(discord_id)
            }
        )
        if 'Item' in response:
            return set(response['Item'].get('solvedProblems', []))
        return set()
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return set()
    
def get_solved_problems(discord_id, cf_username):
    solved_problems = get_stored_solved_problems(discord_id)
    if len(solved_problems) == 0:    
      user_status_url = f'https://codeforces.com/api/user.status?handle={cf_username}&from=1'
      response = requests.get(user_status_url)
      if response.status_code == 200:
          submissions = response.json()['result']
          for submission in submissions:
              if submission['verdict'] == 'OK':
                  # Construct the unique identifier for the problem
                  problem_id = f"{submission['problem']['contestId']}{submission['problem']['index']}"
                  solved_problems.add(problem_id)
      else:
          print(f"Failed to fetch user's solved problems. Status Code: {response.status_code}")
    return solved_problems
        
def store_user(discord_id, cf_handle):
    try:
        response = DiscordID_table.put_item(
            Item={
                'discordID': str(discord_id),  # Ensure it's a string
                'codeforcesHandle': cf_handle
            }
        )
        return True, "User information stored successfully."
    except Exception as e:
        return False, f"An error occurred: {str(e)}"

def store_solved_problems(discord_id, solved_problems):
    try:
        response = solved_problems_table.put_item(
            Item={
                'discordID': str(discord_id),  # Ensure it's a string
                'solvedProblems': list(solved_problems)  # Store as a list
            }
        )
        return True, "Solved problems stored successfully."
    except Exception as e:
        return False, f"An error occurred: {str(e)}"

def get_cf_handle_from_db(discord_id):
    try:
        response = DiscordID_table.get_item(Key={'discordID': str(discord_id)})
        if 'Item' in response:
            return response['Item'].get('codeforcesHandle')
        return None
    except Exception as e:
        print(f"Error fetching Codeforces handle: {str(e)}")
        return None

RATING_COLORS = {
    (0, 1199): ('Gray', 0xCCCCCC),
    (1200, 1399): ('Green', 0x77FF77),
    (1400, 1599): ('Cyan', 0x03a89e),
    (1600, 1899): ('Blue', 0xAAAAFF),
    (1900, 2099): ('Violet', 0xa0a),
    (2100, 2399): ('Orange', 0xff8c00),
    (2400, 9999): ('Red', 0xFF0000),
}

def get_codeforces_rating(username):
    api_url = f"https://codeforces.com/api/user.info?handles={username}"
    response = requests.get(api_url)
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'OK':
            return data['result'][0]['rating']
        else:
            print("Error in API response:", data['comment'])
            return None
    else:
        print("Failed to retrieve data from Codeforces API")
        return None
    
async def set_discord_role_color(member, rating):
    color_name = None
    for rating_range, (color_name, color_value) in RATING_COLORS.items():
        if rating_range[0] <= rating <= rating_range[1]:
            role_name = f"Rating {rating_range[0]}-{rating_range[1]}"
            role = discord.utils.get(member.guild.roles, name=role_name)
            if not role:
                role = await member.guild.create_role(name=role_name, color=discord.Color(color_value))
            else:
                await role.edit(color=discord.Color(color_value))

            await member.add_roles(role)
            return color_name
    return "Unknown"  # If rating does not fall into any predefined range


@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    print(f"Message from {message.author}: {message.content}")

    if message.content.startswith('!identify'):
        discord_user_id = str(message.author.id)
        content = message.content.strip()

        if len(content.split()) > 1:
            _, cf_username = content.split(' ', 1)
            success, response = store_user(discord_user_id, cf_username)
            if not success:
                raise Exception(response)

            solved_problems = get_solved_problems(discord_user_id, cf_username)
            store_success, store_response = store_solved_problems(discord_user_id, solved_problems)
            if not store_success:
                await message.channel.send(store_response)

            response = f"Codeforces username for {message.author.display_name} set to {cf_username}."
        else:
            cf_username = get_cf_handle_from_db(discord_user_id)
            if cf_username:
                solved_problems = get_solved_problems(discord_user_id, cf_username)
                store_success, store_response = store_solved_problems(discord_user_id, solved_problems)
                if not store_success:
                    await message.channel.send(store_response)
                response = f"Fetched {len(solved_problems)} solved problems for {cf_username}."
            else:
                response = "You have not identified your Codeforces handle yet. Use 'identify [username]' to set it."

        await message.channel.send(response)

    if message.content.startswith('!problem'):
        discord_user_id = message.author.id
        cf_username = get_cf_handle_from_db(discord_user_id)
        if cf_username:
            solved_problems = get_solved_problems(discord_user_id, cf_username)
            try:
                _, min_difficulty, max_difficulty = message.content.split()
                min_difficulty = int(min_difficulty)
                max_difficulty = int(max_difficulty)
                problem_details = get_random_problem(min_difficulty, max_difficulty, solved_problems)
                response = f"Problem: {problem_details['name']} (Rating: {problem_details['rating']})\nURL: {problem_details['url']}"
            except ValueError:
                response = "Please provide valid difficulty levels in the format: problem [min_difficulty] [max_difficulty]"
            except Exception as e:
                response = f"An error occurred: {problem_details}"
        else:
            response = "Please identify yourself first with your Codeforces username using the command: identify [username]"

        await message.channel.send(response)

    if message.content.startswith('!rating'):
        cf_username = message.content.split()[1]
        rating = get_codeforces_rating(cf_username)
        if rating is not None:
            color_name = await set_discord_role_color(message.author, rating)
            await message.channel.send(f"{cf_username} has rating {rating}, color is set to {color_name}")
        else:
            await message.channel.send("Could not retrieve Codeforces rating.")

client.run(os.getenv('BOT_TOKEN'))
