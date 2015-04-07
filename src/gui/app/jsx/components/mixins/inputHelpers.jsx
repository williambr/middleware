// INPUT HELPER MIXIN
// ==================
// Provides utility functions for generating common parts of input fields.

"use strict";

var _ = require("lodash");
var React = require("react");

module.exports = {

    // Takes an array and turns it into an array of options suitable for use
    // in a select box or multi-select box.
    generateOptionsList: function (optionArray) {
      var optionList = _.map(optionArray, function( opt ) {
        return ( <option>{opt.name}</option> );
      }, this);

      return optionList;
    }

    // Check if a given attribute is mutable according to the given data keys.
    // This is a PITA because this information is buried in an object in an
    // array in a prop, which cannot be helped.
  , isMutable: function (attribute, dataKeys) {
      return (_.find(dataKeys, function (dataKey) {
        return (dataKey.key === attribute);
      }, this).mutable);
    }

    // Returns an object containin the mutable fields from the item in nextProps.
    // A malformed nextProps will result in an empty array.
  , removeReadOnlyFields: function(item, keys) {
      var outgoingItem = {};
      // Used to put all the old fields into the new object, unless they're immutable
      outgoingItem = _.pick( item, function (value, key) {
        if (keys[key]) {
          return keys[key]["mutable"];
        } else {
          // Do not accept unknown properties from the Middleware.
          // TODO: If we want to accept arbitrary properies, we will need more
          // sophisticated handling here.
          console.warn("Received an unknown property \"" + key + "\" from the Middleware Server.");
          console.warn(this.props.item);
          return false;
        }
      }, this  );
      return outgoingItem;
    }
};