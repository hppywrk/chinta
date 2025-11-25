#pragma once

#include <cpprest/http_listener.h>
#include <cpprest/json.h>
#include <memory>
#include <string>

namespace httpservice {
    
class HttpServer {
public:
    HttpServer(const std::string& address, const std::string& port);
    virtual ~HttpServer();
    
    void start();
    void stop();
    
protected:
    virtual void setup_routes() = 0;
    void add_route(const std::string& path, const web::http::method& method, 
                   std::function<void(web::http::http_request)> handler);
    
private:
    web::http::experimental::listener::http_listener listener_;
};

} // namespace httpservice