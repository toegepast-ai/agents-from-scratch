from typing import Literal

from langchain.chat_models import init_chat_model

from langgraph.graph import StateGraph, START, END
from langgraph.store.base import BaseStore
from langgraph.types import interrupt, Command

from email_assistant.tools import get_tools, get_tools_by_name
from email_assistant.tools.gmail.prompt_templates import TOOLS_TWEEDEKAMER_PROMPT
from email_assistant.tools.gmail.gmail_tools import mark_as_read
from email_assistant.tools.default.tweedekamer_tools import (
    search_kamerleden,
    get_kamerstukken, 
    search_vergaderingen,
    get_stemmingen,
    search_commissies,
    clarification_tool
)
from email_assistant.prompts import (
    triage_system_prompt, 
    triage_user_prompt, 
    tweedekamer_background, 
    tweedekamer_triage_instructions, 
    agent_system_prompt_tweedekamer,
    tweedekamer_response_preferences,
    MEMORY_UPDATE_INSTRUCTIONS, 
    MEMORY_UPDATE_INSTRUCTIONS_REINFORCEMENT
)
from email_assistant.schemas import State, RouterSchema, StateInput, UserPreferences
from email_assistant.utils import parse_gmail, format_for_display, format_gmail_markdown
from dotenv import load_dotenv

load_dotenv(".env")

# Get Gmail tools + Dutch Parliament tools
gmail_tools = get_tools(["send_email_tool", "Question", "Done"], include_gmail=True)
tweedekamer_tools = [search_kamerleden, get_kamerstukken, search_vergaderingen, get_stemmingen, search_commissies, clarification_tool]

# Combine all tools
tools = gmail_tools + tweedekamer_tools
tools_by_name = get_tools_by_name(tools)

# Initialize the LLM for use with router / structured output
llm = init_chat_model("openai:gpt-4.1", temperature=0.0)
llm_router = llm.with_structured_output(RouterSchema) 

# Initialize the LLM, enforcing tool use (of any available tools) for agent
llm = init_chat_model("openai:gpt-4.1", temperature=0.0)
# Add strict tool choice to prevent multiple tool calls in server context
llm_with_tools = llm.bind_tools(tools, tool_choice="auto", parallel_tool_calls=False)

def get_memory(store, namespace, default_content=None):
    """Get memory from the store or initialize with default if it doesn't exist.
    
    Args:
        store: LangGraph BaseStore instance to search for existing memory
        namespace: Tuple defining the memory namespace, e.g. ("tweedekamer_assistant", "triage_preferences")
        default_content: Default content to use if memory doesn't exist
        
    Returns:
        str: The content of the memory profile, either from existing memory or the default
    """
    # Search for existing memory with namespace and key
    user_preferences = store.get(namespace, "user_preferences")
    
    # If memory exists, return its content (the value)
    if user_preferences:
        return user_preferences.value
    
    # If memory doesn't exist, add it to the store and return the default content
    else:
        # Namespace, key, value
        store.put(namespace, "user_preferences", default_content)
        user_preferences = default_content
    
    # Return the default content
    return user_preferences 

def update_memory(store, namespace, messages):
    """Update memory profile in the store.
    
    Args:
        store: LangGraph BaseStore instance to update memory
        namespace: Tuple defining the memory namespace, e.g. ("tweedekamer_assistant", "triage_preferences")
        messages: List of messages to update the memory with
    """
    # Get the existing memory
    user_preferences = store.get(namespace, "user_preferences")
    # Update the memory
    llm = init_chat_model("openai:gpt-4.1", temperature=0.0).with_structured_output(UserPreferences)
    result = llm.invoke(
        [
            {"role": "system", "content": MEMORY_UPDATE_INSTRUCTIONS.format(current_profile=user_preferences.value, namespace=namespace)},
        ] + messages
    )
    # Save the updated memory to the store
    store.put(namespace, "user_preferences", result.user_preferences)

# Nodes 
def triage_router(state: State, store: BaseStore) -> Command[Literal["triage_interrupt_handler", "response_agent", "__end__"]]:
    """Analyseer email content om te beslissen of we moeten reageren, notificeren, of negeren.

    De triage stap voorkomt dat de assistent tijd verspilt aan:
    - Marketing emails en spam
    - Bedrijfsbrede aankondigingen
    - Berichten bedoeld voor andere teams
    """
    
    # Parse the email input
    author, to, subject, email_thread, email_id = parse_gmail(state["email_input"])
    user_prompt = triage_user_prompt.format(
        author=author, to=to, subject=subject, email_thread=email_thread
    )

    # Create email markdown for Agent Inbox in case of notification  
    email_markdown = format_gmail_markdown(subject, author, to, email_thread, email_id)

    # Search for existing triage_preferences memory
    triage_instructions = get_memory(store, ("tweedekamer_assistant", "triage_preferences"), tweedekamer_triage_instructions)

    # Format system prompt with background and triage instructions
    system_prompt = triage_system_prompt.format(
        background=tweedekamer_background,
        triage_instructions=triage_instructions,
    )

    # Run the router LLM
    result = llm_router.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    # Decision
    classification = result.classification

    # Process the classification decision
    if classification == "respond":
        print("📧 Classification: RESPOND - This email requires a response")
        # Next node
        goto = "response_agent"
        # Update the state
        update = {
            "classification_decision": result.classification,
            "messages": [{"role": "user",
                            "content": f"Respond to the email: {email_markdown}"
                        }],
        }
        
    elif classification == "ignore":
        print("🚫 Classification: IGNORE - This email can be safely ignored")

        # Next node
        goto = END
        # Update the state
        update = {
            "classification_decision": classification,
        }

    elif classification == "notify":
        print("🔔 Classification: NOTIFY - This email contains important information") 

        # Next node
        goto = "triage_interrupt_handler"
        # Update the state
        update = {
            "classification_decision": classification,
        }

    else:
        raise ValueError(f"Invalid classification: {classification}")
    
    return Command(goto=goto, update=update)

def triage_interrupt_handler(state: State, store: BaseStore) -> Command[Literal["response_agent", "__end__"]]:
    """Handles interrupts from the triage step"""
    
    # Parse the email input
    author, to, subject, email_thread, email_id = parse_gmail(state["email_input"])

    # Create email markdown for Agent Inbox in case of notification  
    email_markdown = format_gmail_markdown(subject, author, to, email_thread, email_id)

    # Create messages
    messages = [{"role": "user",
                "content": f"Email to notify user about: {email_markdown}"
                }]

    # Create interrupt for Agent Inbox
    request = {
        "action_request": {
            "action": f"Tweede Kamer Assistant: {state['classification_decision']}",
            "args": {}
        },
        "config": {
            "allow_ignore": True,  
            "allow_respond": True,
            "allow_edit": False, 
            "allow_accept": False,  
        },
        # Email to show in Agent Inbox
        "description": email_markdown,
    }

    # Send to Agent Inbox and wait for response
    response = interrupt([request])[0]

    # If user provides feedback, go to response agent and use feedback to respond to email   
    if response["type"] == "response":
        # Add feedback to messages 
        user_input = response["args"]
        messages.append({"role": "user",
                        "content": f"User wants to reply to the email. Use this feedback to respond: {user_input}"
                        })
        # Update memory with feedback
        update_memory(store, ("tweedekamer_assistant", "triage_preferences"), [{
            "role": "user",
            "content": f"The user decided to respond to the email, so update the triage preferences to capture this."
        }] + messages)

        goto = "response_agent"

    # If user ignores email, go to END
    elif response["type"] == "ignore":
        # Make note of the user's decision to ignore the email
        messages.append({"role": "user",
                        "content": f"The user decided to ignore the email even though it was classified as notify. Update triage preferences to capture this."
                        })
        # Update memory with feedback 
        update_memory(store, ("tweedekamer_assistant", "triage_preferences"), messages)
        goto = END

    # Catch all other responses
    else:
        raise ValueError(f"Invalid response: {response}")

    # Update the state 
    update = {
        "messages": messages,
    }

    return Command(goto=goto, update=update)

def llm_call(state: State, store: BaseStore):
    """LLM decides whether to call a tool or not"""
    
    # Search for existing response_preferences memory
    response_preferences = get_memory(store, ("tweedekamer_assistant", "response_preferences"), tweedekamer_response_preferences)
    
    # Search for existing background memory
    background_info = get_memory(store, ("tweedekamer_assistant", "background"), tweedekamer_background)

    # Circuit breaker: count tool calls made so far
    tool_call_count = 0
    for msg in state["messages"]:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            tool_call_count += len(msg.tool_calls)
    
    # If we've made too many tool calls, force the LLM to provide final answer
    if tool_call_count >= 2:  # Very conservative limit
        # Force no more tools - only send_email_tool allowed
        llm_restricted = llm.bind_tools([tools_by_name["send_email_tool"]], tool_choice="auto")
        system_prompt = agent_system_prompt_tweedekamer.format(
            tools_prompt="You have gathered enough information. Now use send_email_tool to provide your final answer to the user.",
            background=background_info,
            response_preferences=response_preferences
        )
    else:
        llm_restricted = llm_with_tools
        system_prompt = agent_system_prompt_tweedekamer.format(
            tools_prompt=TOOLS_TWEEDEKAMER_PROMPT,
            background=background_info,
            response_preferences=response_preferences
        )

    return {
        "messages": [
            llm_restricted.invoke(
                [{"role": "system", "content": system_prompt}]
                + state["messages"]
            )
        ]
    }

def interrupt_handler(state: State, store: BaseStore) -> Command[Literal["llm_call", "__end__"]]:
    """Creates an interrupt for human review of tool calls"""

    result = []
    goto = "llm_call"

    for tool_call in state["messages"][-1].tool_calls:
        # Allowed tools for HITL
        hitl_tools = ["send_email_tool", "Question", "clarification_tool"]

        # If tool is not in our HITL list, execute it directly without interruption
        if tool_call["name"] not in hitl_tools:
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result.append({"role": "tool", "name": tool_call["name"], "content": observation, "tool_call_id": tool_call["id"]})
            continue

        # Get original email from email_input in state
        email_input = state["email_input"]
        author, to, subject, email_thread, email_id = parse_gmail(email_input)
        original_email_markdown = format_gmail_markdown(subject, author, to, email_thread, email_id)

        # Format tool call for display and prepend the original email
        tool_display = format_for_display(tool_call)
        description = original_email_markdown + tool_display

        # Configure what actions are allowed in Agent Inbox
        if tool_call["name"] == "send_email_tool":
            config = {
                "allow_ignore": True,
                "allow_respond": True,
                "allow_edit": True,
                "allow_accept": True,
            }
        elif tool_call["name"] == "Question":
            config = {
                "allow_ignore": True,
                "allow_respond": True,
                "allow_edit": False,
                "allow_accept": False,
            }
        elif tool_call["name"] == "clarification_tool":
            config = {
                "allow_ignore": True,
                "allow_respond": True,
                "allow_edit": True,
                "allow_accept": True,
            }
        else:
            raise ValueError(f"Invalid tool call: {tool_call['name']}")

        # Create the interrupt request
        request = {
            "action_request": {"action": tool_call["name"], "args": tool_call["args"]},
            "config": config,
            "description": description,
        }

        # Send to Agent Inbox and wait for response
        response = interrupt([request])[0]

        # Handle response types
        if response["type"] == "accept":
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result.append({"role": "tool", "name": tool_call["name"], "content": observation, "tool_call_id": tool_call["id"]})

        elif response["type"] == "edit":
            tool = tools_by_name[tool_call["name"]]
            initial_tool_call = tool_call["args"]
            edited_args = response["args"]["args"]

            ai_message = state["messages"][-1]
            current_id = tool_call["id"]
            updated_tool_calls = [tc for tc in ai_message.tool_calls if tc["id"] != current_id] + [
                {"type": "tool_call", "name": tool_call["name"], "args": edited_args, "id": current_id}
            ]

            result.append(ai_message.model_copy(update={"tool_calls": updated_tool_calls}))

            if tool_call["name"] == "send_email_tool":
                observation = tool.invoke(edited_args)
                result.append({"role": "tool", "name": tool_call["name"], "content": observation, "tool_call_id": current_id})

                update_memory(store, ("tweedekamer_assistant", "response_preferences"), [{
                    "role": "user",
                    "content": f"User edited the email response. Here is the initial email generated by the assistant: {initial_tool_call}. Here is the edited email: {edited_args}. Follow all instructions above, and remember: {MEMORY_UPDATE_INSTRUCTIONS_REINFORCEMENT}."
                }])
            else:
                raise ValueError(f"Invalid tool call: {tool_call['name']}")

        elif response["type"] == "ignore":
            if tool_call["name"] == "send_email_tool":
                result.append({"role": "tool", "name": tool_call["name"], "content": "User ignored this email draft. Ignore this email and end the workflow.", "tool_call_id": tool_call["id"]})
                goto = END
                update_memory(store, ("tweedekamer_assistant", "triage_preferences"), state["messages"] + result + [{
                    "role": "user",
                    "content": f"The user ignored the email draft. That means they did not want to respond to the email. Update the triage preferences to ensure emails of this type are not classified as respond. Follow all instructions above, and remember: {MEMORY_UPDATE_INSTRUCTIONS_REINFORCEMENT}."
                }])

            elif tool_call["name"] == "Question":
                result.append({"role": "tool", "name": tool_call["name"], "content": "User ignored this question. Ignore this email and end the workflow.", "tool_call_id": tool_call["id"]})
                goto = END
                update_memory(store, ("tweedekamer_assistant", "triage_preferences"), state["messages"] + result + [{
                    "role": "user",
                    "content": f"The user ignored the Question. That means they did not want to answer the question or deal with this email. Update the triage preferences to ensure emails of this type are not classified as respond. Follow all instructions above, and remember: {MEMORY_UPDATE_INSTRUCTIONS_REINFORCEMENT}."
                }])
                
            elif tool_call["name"] == "clarification_tool":
                result.append({"role": "tool", "name": tool_call["name"], "content": "User ignored the clarification request. Unable to proceed without more information.", "tool_call_id": tool_call["id"]})
                goto = END
                
            else:
                raise ValueError(f"Invalid tool call: {tool_call['name']}")

        elif response["type"] == "response":
            user_feedback = response["args"]
            if tool_call["name"] == "send_email_tool":
                result.append({"role": "tool", "name": tool_call["name"], "content": f"User gave feedback, which can we incorporate into the email. Feedback: {user_feedback}", "tool_call_id": tool_call["id"]})
                update_memory(store, ("tweedekamer_assistant", "response_preferences"), state["messages"] + result + [{
                    "role": "user",
                    "content": f"User gave feedback, which we can use to update the response preferences. Follow all instructions above, and remember: {MEMORY_UPDATE_INSTRUCTIONS_REINFORCEMENT}."
                }])

            elif tool_call["name"] == "Question":
                result.append({"role": "tool", "name": tool_call["name"], "content": f"User answered the question, which can we can use for any follow up actions. Feedback: {user_feedback}", "tool_call_id": tool_call["id"]})

            elif tool_call["name"] == "clarification_tool":
                # User provided clarification - add to messages for next llm_call
                clarification_response = f"User provided clarification: {user_feedback}"
                result.append({"role": "tool", "name": tool_call["name"], "content": clarification_response, "tool_call_id": tool_call["id"]})
                
                result.append({
                    "role": "user", 
                    "content": f"Aanvullende informatie ontvangen: {user_feedback}. Gebruik deze informatie nu om de juiste API call uit te voeren."
                })

            else:
                raise ValueError(f"Invalid tool call: {tool_call['name']}")

    update = {"messages": result}
    return Command(goto=goto, update=update)

# Conditional edge function
def should_continue(state: State, store: BaseStore) -> Literal["interrupt_handler", "mark_as_read_node"]:
    """Route to tool handler, or end if Done tool called"""
    messages = state["messages"]
    last_message = messages[-1]
    
    # Check for tool calls
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        for tool_call in last_message.tool_calls: 
            if tool_call["name"] == "Done":
                return "mark_as_read_node"
            else:
                return "interrupt_handler"
    
    # Default: mark as read (no tool calls means we're done)
    return "mark_as_read_node"

def mark_as_read_node(state: State):
    """Mark email as read after processing."""
    email_input = state["email_input"]
    author, to, subject, email_thread, email_id = parse_gmail(email_input)
    
    # Only mark as read if it's a real Gmail ID (not a test/mock ID)
    if email_id and not email_id.startswith(('test-', 'langsmith-', 'mock-', 'debug-')):
        try:
            mark_as_read(email_id)
            print(f"✅ Email {email_id} marked as read")
        except Exception as e:
            print(f"⚠️ Could not mark email {email_id} as read: {e}")
    else:
        print(f"⏭️ Skipping mark as read for test email ID: {email_id}")

# Build workflow
agent_builder = StateGraph(State)

# Add nodes - with store parameter
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("interrupt_handler", interrupt_handler)
agent_builder.add_node("mark_as_read_node", mark_as_read_node)

# Add edges
agent_builder.add_edge(START, "llm_call")
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
    {
        "interrupt_handler": "interrupt_handler",
        "mark_as_read_node": "mark_as_read_node",
    },
)
agent_builder.add_edge("mark_as_read_node", END)

# Compile the agent
response_agent = agent_builder.compile()

# Build overall workflow
overall_workflow = (
    StateGraph(State, input=StateInput)
    .add_node(triage_router)
    .add_node(triage_interrupt_handler)
    .add_node("response_agent", response_agent)
    .add_node("mark_as_read_node", mark_as_read_node)
    .add_edge(START, "triage_router")
    .add_edge("mark_as_read_node", END)
)

# Compile with interrupts for HITL and recursion limit
email_assistant = overall_workflow.compile()
