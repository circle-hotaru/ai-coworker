#pragma once
#include "passive_notify_server.h"

class ReviewerNotifyServer : public PassiveNotifyServer {
public:
    ReviewerNotifyServer() : PassiveNotifyServer("Reviewer") {}
};
