# Introduction

This is a pure Python version of Graphviz with enhancements for interactive layout.

The purpose of this work is to run the original code in pure python form to: 
* explore and understand the Graphviz code.
* explore the data structures
* modernize the code to use a language (python) with a built-in garbage collection
* reduce the complexity of the data structures to use standard Python built in types like dict and sets
* pull out the layout tools to allow them to be used in an interactive GUI library (PyQt)

This allows user interaction with the graph and a means of using visual feedback and node 
freezing for doing graphical layout.  In addition this enables _time based_ analysis of the graph properties by
allowing the layout formation to be captured over time. Many insights can be abotained by time based simulation 
and observations. 

## Original Code
The original code is obtained here:
https://graphviz.org/download/

In addition the root of the source code is located in the gzip file here:

file://graphviz-12.2.1.tar.gz/graphviz-12.2.1/lib

This has been moved to teh gc package in python.


# Code Structure
The code has been translated verbetim from c to Python 3.9+ using the c2python tool set. 

The include methods are changed to incorporate a single data structure 
file called _allDataStructs.py_. This eliminates some of the circular nature of the imports across the modules.
In addition the class dependencies are easier to maintain. 

The naming convention of the modules matches the naming convention of the original c code where possible.
Data structures have there first character capitalized to match the PEP 8 conventions.
Data types are defined using the Typing module. Enums are defined using the Enum class.


# Layouts
The layout algorithms are rewritten to enable hooks back into an event driven GUI framework.


Graphviz provides several layout algorithms that you can use to visualize your graphs:

- dot: A hierarchical layout algorithm designed to produce readable and compact 
visualizations of directed graphs with a clear top-to-bottom or left-to-right structure.

- neato: A force-directed layout algorithm that uses a spring-electrical model 
to position nodes in a way that minimizes the energy of the system and reduces edge crossings.

- twopi: A radial layout algorithm that positions nodes in concentric circles 
around a central node. The distance of each node from the center of the layout is based on its 
distance from the central node in the graph.

- circo: A circular layout algorithm that positions nodes around a circle and 
minimizes the number of edge crossings by optimizing the order of nodes around the circle.

- fdp: A force-directed layout algorithm similar to neato, but with a 
different optimization strategy.

- sfdp: A multiscale version of the fdp layout algorithm that is designed to handle large and complex graphs 
by gradually increasing the level of detail in the layout.

- patchwork: A layout algorithm that combines rectangular subgraphs into a larger 
layout.


Each of these layout algorithms has its own strengths and weaknesses, and the 
best choice depends on the specific requirements of your graph and the desired 
outcome of your visualization.