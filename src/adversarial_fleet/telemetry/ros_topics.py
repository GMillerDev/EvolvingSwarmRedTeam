"""Verified Open-RMF Kilted topic names used by the external collector."""

FLEET_STATES = "/fleet_states"
DISPATCH_STATES = "/dispatch_states"
TASK_STATE_UPDATE = "/task_state_update"
TASK_API_REQUESTS = "/task_api_requests"
TASK_API_RESPONSES = "/task_api_responses"
DOOR_STATES = "/door_states"
LIFT_STATES = "/lift_states"
CLOSED_LANES = "/closed_lanes"
LANE_CLOSURE_REQUESTS = "/lane_closure_requests"
LANE_STATES = "/lane_states"
TRAFFIC_BID_NOTICE = "/rmf_task/bid_notice"
TRAFFIC_BID_RESPONSE = "/rmf_task/bid_response"
TRAFFIC_DISPATCH_REQUEST = "/rmf_task/dispatch_request"
TRAFFIC_DISPATCH_ACK = "/rmf_task/dispatch_ack"

REQUIRED_TOPICS = frozenset({FLEET_STATES, DISPATCH_STATES, TASK_STATE_UPDATE})

ROSBAG_TOPICS = (
    "/clock",
    FLEET_STATES,
    "/fleet_state_update",
    DISPATCH_STATES,
    TASK_STATE_UPDATE,
    TASK_API_REQUESTS,
    TASK_API_RESPONSES,
    DOOR_STATES,
    LANE_CLOSURE_REQUESTS,
    CLOSED_LANES,
    LANE_STATES,
    TRAFFIC_BID_NOTICE,
    TRAFFIC_BID_RESPONSE,
    TRAFFIC_DISPATCH_REQUEST,
    TRAFFIC_DISPATCH_ACK,
    "/rmf_traffic/negotiation_notice",
    "/rmf_traffic/negotiation_proposal",
    "/rmf_traffic/negotiation_conclusion",
    "/rmf_traffic/negotiation_statuses",
)
