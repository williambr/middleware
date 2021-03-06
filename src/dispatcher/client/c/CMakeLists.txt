cmake_minimum_required(VERSION 2.8)

project (dispatcherclient)
set(CMAKE_BUILD_TYPE Debug)

find_package (Threads)
find_package(PkgConfig)
pkg_check_modules(JANSSON REQUIRED jansson)
pkg_search_module(JANSSON jansson)
include_directories(${JANSSON_INCLUDE_DIRS})
link_directories(${JANSSON_LIBRARY_DIRS})
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/src)

add_library(dispatcherclient SHARED src/ws.c src/dispatcher.c)
target_link_libraries(dispatcherclient ${JANSSON_LIBRARIES})
target_link_libraries (dispatcherclient ${CMAKE_THREAD_LIBS_INIT})

add_executable(wstest examples/wstest.c)
target_link_libraries(wstest readline)
target_link_libraries(wstest dispatcherclient)

add_executable(enum examples/enum.c)
target_link_libraries(enum dispatcherclient)

add_executable(listen examples/listen.c)
target_link_libraries(listen dispatcherclient)